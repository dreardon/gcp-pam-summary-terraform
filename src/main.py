import json
import time
import base64
import os
import requests
from datetime import datetime
import markdown
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from google.api_core.exceptions import NotFound, AlreadyExists, Conflict, ResourceExhausted
from google.cloud import logging, bigquery, privilegedaccessmanager_v1
from google.cloud.logging import DESCENDING
from google.cloud.asset_v1 import AssetServiceClient, SearchAllResourcesRequest
from googleapiclient.discovery import build
from flask import Flask, request
import google.auth.transport.requests
from google.auth import compute_engine


app = Flask(__name__)

summary_project_id = os.environ.get("PROJECT_ID", "Project ID not set in Cloud Run Function environment variable")
region = os.environ.get("REGION", "Region not set in Cloud Run Function environment variable")
summary_recipient = os.environ.get("SUMMARY_RECIPIENT", "Summary recipient not set in Cloud Run Function environment variable")

@app.route("/", methods=["POST"])
def index(*args, **kwargs):
    envelope = request.get_json()
    if not envelope:
        msg = "No Pub/Sub Message Received"
        print(f"error: {msg}")
        return f"Bad Request: {msg}", 400

    if not isinstance(envelope, dict) or "message" not in envelope:
        msg = "Invalid Pub/Sub Message Format"
        return f"Bad Request: {msg}", 400
    pubsub_message = envelope["message"]
    
    if isinstance(pubsub_message, dict) and "data" in pubsub_message:
        name = base64.b64decode(pubsub_message["data"]).decode("utf-8").strip()
        message = json.loads(name)
        grant_message = message['protoPayload']['resourceName']
    
    grant = get_pam_grants(grant_message)
    grantee = grant['requester']
    if grant['state'] in ['ACTIVE']:
        create_log_router_and_destination(grant)
    elif grant['state'] in ['REVOKED','ENDED']:
        delete_log_router(grant)
        grant_activity = get_pam_activities(grant)
        add_to_bq(grant_activity)
        summary = generate_summary(summary_project_id, grant_activity)
        send_notification(grantee,summary)
    else:
        print('PAM Message State must be "ACTIVE","ENDED", or "REVOKED", the status was:',grant['state'])

    return ("PAM Grant Summary Processed Successfully", 200)

def add_to_bq(grant_activity):
    bigquery_client = bigquery.Client()
    dataset = create_bq_dataset(grant_activity)

    table_id = "{}.{}.summary_table".format(summary_project_id,dataset.dataset_id)
    table = bigquery.Table(table_id)

    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("project_name", "STRING"),
            bigquery.SchemaField("project_id", "STRING"),
            bigquery.SchemaField("service_name", "STRING"),
            bigquery.SchemaField("method_name", "STRING"),
            bigquery.SchemaField("resource_name", "STRING"),
            bigquery.SchemaField("during_pam_grant", "BOOL")
        ],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )  
    print("Number of Activities to Add to Table {}: {}".format(table_id,len(grant_activity['activities'])))
    bigquery_client.load_table_from_json(grant_activity['activities'],table,job_config=job_config)
    print('Added Activity Logs to Bigquery Dataset {}'.format(dataset.dataset_id))

def delete_log_router(grant):
    logging_client = logging.Client()
    custom_startdate = datetime.fromisoformat(grant['start_time']).strftime('%Y%m%d_%H%M%S')
    sink_name = 'grant_'+custom_startdate+'_'+grant['name'].split('/')[-1].replace('-','_')
    dataset_id = "{}.{}".format(summary_project_id,sink_name)
    dataset = bigquery.Dataset(dataset_id)
    
    #Delete Log Sink
    try:
        sink_scope = grant['roles_scope'].replace('//cloudresourcemanager.googleapis.com/','')

        sink = logging.Sink(
            sink_name,
            parent=sink_scope,
            client=logging_client)

        sink.delete()
        print("Deleted sink {}".format(sink.name))
    except NotFound:
         print("Sink {} not found, skipping deletion".format(sink.name))
         pass
    except Exception as e:
        print(e)
        print('Exception Type is:', e.__class__.__name__)
        pass

def create_bq_dataset(grant):
    bigquery_client = bigquery.Client()
    custom_startdate = datetime.fromisoformat(grant['start_time']).strftime('%Y%m%d_%H%M%S')
    sink_name = 'grant_'+custom_startdate+'_'+grant['name'].split('/')[-1].replace('-','_')
    dataset_id = "{}.{}".format(summary_project_id,sink_name)

    try:
        dataset = bigquery.Dataset(dataset_id)
        dataset.location = region
        dataset.description = "PAM grant activity dataset for {} when given the grant {}".format(grant['requester'], grant['name'])
        dataset = bigquery_client.create_dataset(dataset, timeout=30)
        print("Created dataset {}.{}".format(summary_project_id, dataset.dataset_id))
    except Conflict:
        print('BigQuery Dataset {}.{} already exists'.format(summary_project_id, dataset.dataset_id))
        pass
    except Exception as e:
        print(e)
        print('Exception Type is:', e.__class__.__name__)
        pass
    
    return dataset

#TODO Most likely OBE based on latency of log delivery after instantiation
def create_log_router_and_destination(grant):
    bigquery_client = bigquery.Client()
    logging_client = build('logging', 'v2')

    #Create Dataset
    dataset = create_bq_dataset(grant)

    #Create Log Sink
    destination = "bigquery.googleapis.com/projects/{0}/datasets/{1}".format(summary_project_id,dataset.dataset_id)
    sink_scope = grant['roles_scope'].replace('//cloudresourcemanager.googleapis.com/','')
    include_children = False
    if sink_scope.split('/')[0] != 'projects':
        include_children = True
    try:
        FILTER = '''
            protoPayload.authenticationInfo.principalEmail={0}
            '''.format(grant['requester'])

        sink = logging_client.sinks().create(parent=sink_scope,uniqueWriterIdentity=True,
            body={
                'name':dataset.dataset_id,
                'filter':FILTER,
                'destination':destination,
                'includeChildren':include_children
            }).execute()

        print("Created sink {} at {}".format(sink['name'],sink_scope))
    except Exception as e:
        print(e)
        print('Exception Type is:', e.__class__.__name__)
        pass

    #Give Log Sink Write Permissions to Dataset
    try:
        role = "roles/bigquery.dataEditor"
        access_entries = dataset.access_entries
        access_entries.append(
            bigquery.AccessEntry(role, "userByEmail", sink['writerIdentity'].split(':')[1])
        )
        dataset.access_entries = access_entries
        dataset = bigquery_client.update_dataset(dataset, ["access_entries"])
        print(f"Role {role} granted to {sink['writerIdentity']} on dataset {dataset.full_dataset_id}")
    except Exception as e:
        print(e)
        print('Exception Type is:', e.__class__.__name__)
        pass

def get_pam_grants(grant_message):
    pam_client = privilegedaccessmanager_v1.PrivilegedAccessManagerClient()
    
    result = pam_client.get_grant(name=grant_message)

    grant = {}
    grant['name'] = result.name
    grant['requester'] = result.requester
    grant['duration_in_seconds'] = result.requested_duration.seconds
    grant['state'] = result.state.name
    grant['justification'] = result.justification.unstructured_justification or ""
    grant['roles'] = result.privileged_access.gcp_iam_access.role_bindings[0].role or ""
    grant['roles_scope'] = result.privileged_access.gcp_iam_access.resource or ""
    grant['start_time'] = result.audit_trail.access_grant_time.isoformat() or ""
    try:
        grant['end_time'] = result.audit_trail.access_remove_time.isoformat()
    except:
        grant['end_time'] = ""
    return grant

def get_pam_activities(grant):
    print('Current Grant'.format(grant))
    current_grant = grant
    current_grant['activities'] = []
    start_datetime=grant.get('start_time')
    end_datetime=grant.get('end_time', "")
    FILTER = '''
        protoPayload.authenticationInfo.principalEmail={0} AND
        timestamp>="{1}" AND timestamp<="{2}"
        '''.format(grant['requester'],start_datetime,end_datetime)

    cai_client = AssetServiceClient()
    grant_scope = grant['roles_scope'].replace('//cloudresourcemanager.googleapis.com/','')
    request = SearchAllResourcesRequest(
        scope=grant_scope,
        asset_types=[
            "cloudresourcemanager.googleapis.com/Project",
        ],
        query="state:ACTIVE",
    )

    paged_results = cai_client.search_all_resources(request=request)

    for response in paged_results:
        counter = 0
        project_id = response.name.split("/")[4]
        print('Response: {}'.format(response))
        print('Fetching logs for project {}'.format(project_id))
        print('Using Filter: {}'.format(FILTER))
        logging_client = logging.Client(project=project_id)
        try:
            iterator = logging_client.list_entries(filter_=FILTER, order_by=DESCENDING)
            for entry in iterator:
                counter += 1
                entry = entry.to_api_repr()
                activity = {}
                activity["project_name"] = response.display_name
                activity["project_id"] = project_id
                activity["service_name"] = entry.get('protoPayload', {}).get('serviceName', "")
                activity["method_name"] = entry.get('protoPayload', {}).get('methodName', "")
                activity["resource_name"] = entry.get('protoPayload', {}).get('resourceName', "")
                activity["timestamp"] = entry['timestamp']
                current_grant["activities"].append(activity)
            print('Collected {} entries in project {}'.format(counter,project_id))
        except ResourceExhausted:
            print("Hit log read limit, try again in 1 minute")
            time.sleep(60)
            continue
        except Exception as e:
            print(e)
            print('Exception Type is:', e.__class__.__name__)        
    return current_grant

#TODO Explore Response Schemas as a way to control generation
def generate_summary(summary_project_id, activity):

    vertexai.init(project=summary_project_id, location="us-central1")
    print('PAM Summary Type:', type(activity))
    
    model = GenerativeModel(
        "gemini-2.0-flash-001",
    )

    response_schema = {
        "type": "object",
        "properties": {
            "summary_response": {"type": "string"},
            "name": {"type": "string"},
            "justification": {"type": "string"},
            "duration": {"type": "string"},
            "roles": {"type": "string"},
            "roles_scope": {"type": "string"},
            "observations_concerns": {"type": "string"},
            }
        }

    prompt = """
            You are a security engineer reviewing a time series of logs for a privileged access management (PAM) grant. Your goal is to identify any activity that warrants further investigation due to potential security risks or policy violations.
            During your review, pay close attention to the following:
            1.  **Data Modification:** Prioritize log entries that involve changes to data, such as updates, creations, deletions, or modifications. These actions often carry a higher risk than read-only operations (e.g., get, list).
            2.  **Privilege Escalation:** Focus on entries where the methods used align with the increased privileges granted by the PAM role(s). Look for any misuse or abuse of these elevated permissions.
            3.  **Unexpected Resource Access:** Identify any attempts to access resources outside the intended scope of the PAM grant. This could indicate unauthorized activity or a misunderstanding of the grant's limitations.
            4.  **High-Risk Operations:** Be particularly vigilant for operations known to pose significant security risks, such as:
                *   Changes to IAM policies or permissions.
                *   Modifications to critical system configurations.
                *   Access or modification of sensitive data stores.
                *   Creation or execution of compute instances or functions.
                *   Network configuration changes.
            5.  **Unusual Patterns:** Look for any patterns or sequences of actions that seem out of the ordinary or deviate from expected behavior within the context of the PAM grant.
            For each log entry, consider the following questions:
            *   Does this action align with the stated justification for the PAM grant?
            *   Could this action potentially compromise the security or integrity of the system or its data?
            *   Is there any indication of malicious intent or accidental misuse of privileges?

            Based on your analysis, flag any log entries that raise security concerns and provide a brief explanation of why they warrant further attention.{}
        """.format(activity.get('roles'),json.dumps(activity))
    
    generation_config = GenerationConfig(
        #response_mime_type="application/json",
        #response_schema=response_schema,
        max_output_tokens=8192,
        temperature=1,
        top_p=0.95,
    )

    response = model.generate_content(
        prompt,
        generation_config=generation_config,
    )

    print('Summary Response:', response.text)

    return response.text

def send_notification(grantee, summary):
    def token_from_metadata_server():
        request = google.auth.transport.requests.Request()
        credentials = compute_engine.Credentials()
        credentials.refresh(request)
        return credentials.token

    llm_caveat = "<sup>This content was generated with the assistance of an AI language model. While we strive for accuracy, it may contain errors or biases. Please review and verify the information before use.<sup>"
    summary = summary + '\n' + llm_caveat
    access_token = token_from_metadata_server()
    api_endpoint = 'api_trigger/pam-summary-email'
    pam_user = grantee
    app_int_endpoint = 'https://{0}-integrations.googleapis.com/v1/projects/{1}/locations/{0}/integrations/-:execute'.format(region,summary_project_id)
    app_int_config = {"trigger_id": api_endpoint,
        "input_parameters": { "recipient": {"string_value": summary_recipient }, 
            "pam_user" : {"string_value" : pam_user}, 
            "email_content" : {"string_value" : markdown.markdown(summary)}
            }
        }
    
    headers = {"Authorization": "Bearer " + access_token, "Content-Type": "application/json"} 
    requests.post(app_int_endpoint, json=app_int_config, headers=headers)
    print('Sent Notification')

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))