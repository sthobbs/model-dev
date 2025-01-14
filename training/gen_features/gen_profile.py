
from gcp_helpers.storage import Storage
from gcp_helpers.bigquery import BigQuery
from gcp_helpers.logger import Logger
from config import project_id, dataset_id, bucket_name, query_params
from utils.parallel import parallelize_threads
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path

# setup logger
logger = Logger(project_id).logger

date_format = '%Y-%m-%d'


def gen_profile(end_date):
    """
    Generate a customer profile for a given end_date, upload to GCS,
    then remove from BigQuery.

    Parameters
    ----------
    end_date : datetime.datetime
        End date for the profile
    """

    # set destination table name based on end_date
    dest_table_id = f"profile_{end_date.strftime('%Y%m%d')}"

    # update query date params
    cur_query_params = query_params.copy()
    cur_query_params['start_date'] = (end_date - relativedelta(years=1)).strftime(date_format)
    cur_query_params['end_date'] = end_date.strftime(date_format)

    # get query from file and pass in query parameters
    query_path = "./training/gen_features/sql/profile/gen_profile.sql"
    with open(query_path, 'r') as file:
        query = file.read().format(**cur_query_params)

    # instantiate BigQuery API helper
    t = BigQuery(project_id=project_id,
                 dataset_id=dataset_id,
                 table_id=dest_table_id,
                 logger=logger)
    
    # run queries
    t.query(query, dest_table_id=dest_table_id)

    # upload to GCS
    gcs_uri = f"gs://{bucket_name}/profiles/profile_{end_date.strftime(date_format)}.json"
    t.extract_to_gcs(gcs_uri, dest_format=None)

    # delete table
    t.delete_table()


def run():
    """Generate all monthly customer profiles."""

    # get all monthly end_date values for query param
    params = []
    curr = datetime.strptime(query_params['start_date'], date_format)  # current end date
    end_date = datetime.strptime(query_params['end_date'], date_format)  # end date
    while curr < end_date:
        curr += relativedelta(months=1)
        params.append({'end_date': curr})

    # Generate customer profiles for each month in parallel
    parallelize_threads(gen_profile, params)

    # Load all customer profiles into one BigQuery table
    t = BigQuery(project_id=project_id,
                 dataset_id=dataset_id,
                 table_id='profile',
                 schema_json_path='./training/gen_features/schemas/profile.json',
                 logger=logger)
    gcs_uri = f"gs://{bucket_name}/profiles/profile_*.json"
    t.load_from_gcs(gcs_uri, source_format='JSON', partition_field='profileDate')

    # Copy profile from GCS to local machine
    s = Storage(project_id=project_id, bucket_name=bucket_name, logger=logger)
    local_dest_dir = Path('./data/profiles')  # path to directory where profile data will be saved
    local_dest_dir.mkdir(parents=True, exist_ok=True)
    gcs_src_paths = s.list_blobs(prefix="profiles/profile_")
    for gcs_src_path in gcs_src_paths:
        local_dest_path = local_dest_dir / Path(gcs_src_path).name
        s.download_blob(gcs_src_path, local_dest_path)


if __name__ == '__main__':
    run()

