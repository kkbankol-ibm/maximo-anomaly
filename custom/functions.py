import inspect
import logging
import datetime as dt
import math
from sqlalchemy.sql.sqltypes import TIMESTAMP,VARCHAR
import numpy as np
import pandas as pd
import json
import base64
import requests

#from iotfunctions.base import BaseTransformer
from iotfunctions.base import BasePreload
from iotfunctions.base import BaseTransformer
from iotfunctions import ui
from iotfunctions.db import Database
from iotfunctions import bif
#import datetime as dt
import datetime
import urllib3
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


# Specify the URL to your package here.
# This URL must be accessible via pip install
PACKAGE_URL = 'git+https://github.com/kkbankol-ibm/monitor-anomaly@'

class InvokeExternalModel(BasePreload):
# class InvokeExternalModel(BaseTransformer):
    '''
    Load entity data, forward to a custom anomaly detection model hosted in Watson Machine Learning service.
    Response returns index of rows that are classified as an anomaly, as well as the confidence score
    '''

    out_table_name = None

    def __init__(self, wml_endpoint, uid, password, model_id, deployment_id,apikey, input_features, headers = None, body = None, column_map = None, output_item  = 'http_preload_done'):
    # def __init__(self, model_url, headers = None, body = None, column_map = None, output_item  = 'http_preload_done'):
        if body is None:
            body = {}

        if headers is None:
            headers = {}

        if column_map is None:
            column_map = {}

        super().__init__(dummy_items=[],output_item = output_item)

        # create an instance variable with the IBM IOT Platform Analytics Service Function input arguments.

        self.body = body
        logging.debug('body %s' %body)
        self.column_map = column_map
        logging.debug('column_map %s' %column_map)
        self.wml_endpoint = wml_endpoint
        self.uid = uid
        self.password = password
        self.model_id = model_id
        self.deployment_id = deployment_id
        self.apikey = apikey
        self.input_features = apikey



    '''
    # for invoking custom model if user wants to host outside of IBM Cloud
    def invoke_model(self, df):
        logging.debug('invoking model')
        model_url = self.model_url
        body = df #.to_dict()
        logging.debug('posting dataframe %s' %str(body))
        logging.debug('target %s' %model_url)
        # print("posting following dataframe")
        # print(body)
        # here we need to filter down to the specific fields the user wants.
        return []
        r = requests.post(model_url, json=body)
        if r.status_code == 200:
            logging.debug("predictions received")
            predictions = r.json()
            logging.debug("predictions")
            logging.debug(predictions)
            return predictions
        else:
            logging.debug("failure receiving predictions")
            logging.debug(r.status_code)
            logging.debug(r.text)
            return []
    '''

    def get_iam_token(self, uid, password):
        logging.debug("getting IAM token")
        url     = "https://iam.bluemix.net/oidc/token"
        headers = { "Content-Type" : "application/x-www-form-urlencoded" }
        data    = "apikey=" + apikey + "&grant_type=urn:ibm:params:oauth:grant-type:apikey"
        r = requests.post( url, headers=headers, data=data, auth=( uid, password ) )
        if r.status_code == 200:
            iam_token = r.json()["access_token"]
            print("token received")
            return iam_token
        else:
            print("error retrieving IAM token")
            return None

    def invoke_model(self, df, wml_endpoint, uid, password, model_id, deployment_id, apikey):
        # Taken from https://github.ibm.com/Shuxin-Lin/anomaly-detection/blob/master/Invoke-WML-Scoring.ipynb
        # Get an IAM token from IBM Cloud
        logging.debug("posting enitity data to WML model")
        url     = "https://iam.bluemix.net/oidc/token"
        headers = { "Content-Type" : "application/x-www-form-urlencoded" }
        data    = "apikey=" + apikey + "&grant_type=urn:ibm:params:oauth:grant-type:apikey"
        response  = requests.post( url, headers=headers, data=data, auth=( uid, password ) )
        if 200 != response.status_code:
            logging.error('error getting IAM token')
            logging.error( response.status_code )
            logging.error( response.reason )
            return []
        else:
            logging.debug('token successfully generated')
            iam_token = response.json()["access_token"]
            # Send data to deployed model for processing
            headers = { "Content-Type" : "application/json",
                        "Authorization" : "Bearer " + iam_token,
                        "ML-Instance-ID" : model_id }
            logging.debug("posting to WML")
            columns = ['torque', 'acc', 'load', 'speed', 'tool_type', 'travel_time']
            print("wml df.columns")
            print(df.columns)
            s_df = df[columns]
            rows = [list(r) for i,r in s_df.iterrows()]
            payload = {"values": rows}
            # payload = {"values": df.to_dict()}
            wml_model_endpoint = '%s/v3/wml_instances/%s/deployments/%s/online' %(wml_endpoint, model_id, deployment_id)
            # wml_model_endpoint = f'{wml_endpoint}/w3/wml_instances/{model_id}/deployments/{deployment_id}'
            r = requests.post( wml_model_endpoint, json=payload, headers=headers )
            logging.debug('model response code: ' + str(r.status_code) )
            if r.status_code == 200:
                logging.debug('model response')
                logging.debug(r.text)
                j = r.json()
                logging.debug('json')
                logging.debug(j)
                return j
            else:
                logging.error('error invoking model')
                logging.error(r.status_code)
                logging.error(r.text)
                return None
            # print ( response.text )

    def execute(self, df, start_ts = None,end_ts=None,entities=None):
        # TODO, set time range if not provided. Grab all rows within x hours
        logging.debug('in execution method')
        entity_type = self.get_entity_type()
        logging.debug('entity_type')
        logging.debug(entity_type)
        self.db = entity_type.db
        logging.debug('entity db')
        # encoded_body = json.dumps(self.body).encode('utf-8')
        # encoded_headers = json.dumps(self.headers).encode('utf-8')

        # This class is setup to write to the entity time series table
        # To route data to a different table in a custom function,
        # you can assign the table name to the out_table_name class variable
        # or create a new instance variable with the same name

        if self.out_table_name is None:
            table = entity_type.name
        else:
            table = self.out_table_name
        logging.debug('table')
        logging.debug(table)
        schema = entity_type._db_schema
        logging.debug('schema')


        response_data = {}
        (metrics,dates,categoricals,others) = self.db.get_column_lists_by_type(
            table = table,
            schema= schema,
            exclude_cols = []
        )
        # TODO, can't we also get calculated metrics?
        # logging.debug('all metrics %s ' %metrics)

        # TODO, grabbing all table data for now, add logic to break up by entity id and use start/end_ts values.
        # rows = len(buildings)

        # for m in metrics:
        #     logging.debug('metrics %s ' %m)
        #     # response_data[m] = np.random.normal(0,1,rows)
        #     logging.debug('metrics data %s ' %response_data[m])
        #
        # for d in dates:
        #     logging.debug('dates %s ' %d)
        #     response_data[d] = dt.datetime.utcnow() - dt.timedelta(seconds=15)
        #     logging.debug('dates data %s ' %response_data[d])

        '''
        # Create a timeseries dataframe with data received from Maximo
        '''
        logging.debug('response_data used to create dataframe ===' )
        logging.debug( response_data)
        logging.debug( "dataframe")
        logging.debug( df)
        logging.debug( df.columns)
        if len(df) > 0:
            df = pd.DataFrame(data=df)
        else:
            # test case, pull all simulated data
            table_data = self.db.read_table(table_name=table, schema=schema)
            df = pd.DataFrame(data=table_data) # TODO, shouldn't have to query table, df generally holds the
            logging.debug("loaded df")
            logging.debug(df.columns)

        # add "anomaly_score" column TODO, allow user to customize and provide columns
        # if "anomaly_score" not in df.columns:
        #     df["anomaly_score"] = np.zeros(len(table_data))

        results = self.invoke_model(df.loc[0:99], self.wml_endpoint, self.uid, self.password, self.model_id, self.deployment_id, self.apikey)
        if results:
            logging.debug('results %s' %results )
            # TODO append results to entity table as additional column
            # df.head()["anomaly_score"] =
            # df.loc[0:4,col_indexer]
            df.loc[0:99, 'anomaly_score'] = results['values']
        else:
            logging.error('error invoking external model')
        # logging.debug("exiting after model invoked")
        # return True

        logging.debug('Generated DF from response_data ===' )
        logging.debug( df.head() )
        df = df.rename(self.column_map, axis='columns')
        logging.debug('ReMapped DF ===' )
        logging.debug( df.head() )

        '''
        # Fill in missing columns with nulls
        '''
        required_cols = self.db.get_column_names(table = table, schema=schema)
        # if "anomaly_score" not in required_cols:
        #     required_cols.append('anomaly_score') # TODO, hacky way to add column
        logging.debug('required_cols %s' %required_cols )
        missing_cols = list(set(required_cols) - set(df.columns))
        logging.debug('missing_cols %s' %missing_cols )
        if len(missing_cols) > 0:
            kwargs = {
                'missing_cols' : missing_cols
            }
            entity_type.trace_append(created_by = self,
                                     msg = 'http data was missing columns. Adding values.',
                                     log_method=logger.debug,
                                     **kwargs)
            for m in missing_cols:
                if m==entity_type._timestamp:
                    df[m] = dt.datetime.utcnow() - dt.timedelta(seconds=15)
                elif m=='devicetype':
                    df[m] = entity_type.logical_name
                else:
                    df[m] = None

        '''
        # Remove columns that are not required
        '''
        df = df[required_cols]
        logging.debug('DF stripped to only required columns ===' )
        logging.debug( df )

        '''
        # Write the dataframe to the IBM IOT Platform database table
        '''
        # TODO, need to adjust this logic, possibly to add a column specifying whether row is an anomaly or not?
        # Or write to seperate table
        logging.debug('df.columns')
        logging.debug(df.columns)
        if_exists_action = "replace" # replace # TODO, change to append
        self.write_frame(df=df, table_name=table.lower(), if_exists=if_exists_action)

        # anomaly_table = "anomalies"
        # self.db.create(anomaly_table)
        # self.write_frame(df=df, table_name=anomaly_table)

        kwargs ={
            'table_name' : table,
            'schema' : schema,
            'row_count' : len(df.index)
        }
        logging.debug( "write_frame complete" )
        entity_type.trace_append(created_by=self,
                                 msg='Wrote data to table',
                                 log_method=logger.debug,
                                 **kwargs)
        logging.debug( "appended trace" )
        return True

    '''
    # Create the IOT Platform Function User Interfact input arguements used to connect to the external REST Service.
    # These could be used to connect with any Rest Service to get IOT Data or any other data to include in your dashboards.
    '''
    @classmethod
    def build_ui(cls):
        '''
        Registration metadata
        '''
        # define arguments that behave as function inputs
        inputs = []
        inputs.append(ui.UISingle(name='wml_endpoint',
                              datatype=str,
                              description='Endpoint to WML service where model is hosted',
                              tags=['TEXT'],
                              required=True
                              ))
        inputs.append(ui.UISingle(name='uid',
                              datatype=str,
                              description='IBM Cloud IAM User ID',
                              tags=['TEXT'],
                              required=True
                              ))
        inputs.append(ui.UISingle(name='password',
                              datatype=str,
                              description='IBM Cloud IAM Password',
                              tags=['TEXT'],
                              required=True
                              ))
        inputs.append(ui.UISingle(name='model_id',
                              datatype=str,
                              description='Instance ID for WML model',
                              tags=['TEXT'],
                              required=True
                              ))
        inputs.append(ui.UISingle(name='apikey',
                              datatype=str,
                              description='IBM Cloud API Key',
                              tags=['TEXT'],
                              required=True
                              ))
        inputs.append(ui.UISingle(name='input_features',
                              datatype=str,
                              description='Features to load from entity rows',
                              tags=['TEXT'],
                              required=True
                              ))
        # define arguments that behave as function outputs
        outputs=[]
        outputs.append(ui.UIStatusFlag(name='output_item'))
        return (inputs, outputs)
