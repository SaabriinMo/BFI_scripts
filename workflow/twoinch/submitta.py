#!/usr/bin/env python3

'''
Aggregate candidate selections into optimised batches and submit Workflow jobs
for third Multi Machine Environment in F47 (first was DigiBeta, second was 1inch)

Dependencies:
1. LOGS/2inch_submitta.log
2. twoinch/submissions.csv
3. twoinch/errors.csv
'''

# Public imports
import os
import sys
import csv
import json
import yaml
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Local imports
sys.path.append(os.environ['WORKFLOW'])
import workflow

# Global variables
LOGS = os.environ['LOG_PATH']
TWOINCH = os.path.join(os.environ['WORKFLOW'], 'twoinch/')
NOW = datetime.now()
DT_STR = NOW.strftime("%d/%m/%Y %H:%M:%S")


def check_control():
    '''
    Check downtime control and stop script of False
    '''
    with open(os.path.join(LOGS, 'downtime_control.json')) as control:
        j = json.load(control)
        if not j['pause_scripts']:
            write_to_log(f'Script run prevented by downtime_control.json. Script exiting. {DT_STR}\n')
            sys.exit('Exit requested by downtime_control.json')


def get_csv(csv_path):
    '''
    Open and return data
    '''
    submissions = {}
    with open(csv_path, 'r') as file:
        rows = csv.reader(file)
        for r in rows:
            uid = r[0]
            submissions[uid] = r[1:]
        file.close()

    return submissions


def main():
    '''
    Process all items found in CSV
    '''
    check_control()
    write_to_log(f'=== Processing Items in 2inch selections.csv === {DT_STR}\n')

    # Load configuration variables
    configuration = yaml.safe_load(open(os.path.join(TWOINCH, 'config.yaml'), 'r'))
    batch_size = configuration['Batches']['TapesPerBatch']
    batches_per_iteration = configuration['Batches']['BatchesPerIteration']

    # Submit [iterations] x [size] tapes
    for _ in range(0, batches_per_iteration):

        # Load submissions
        print('* Opening twoinch/submissions csv...')
        submissions = {}
        submissions = get_csv(os.path.join(TWOINCH, 'submissions.csv'))

        # Load selections
        print('* Opening twoinch/selections csv...')
        df = pd.read_csv(os.path.join(TWOINCH, 'selections.csv'))

        # Remove submissions from selections data frame
        print('* Removing 2inch submissions from 2inch selections...')
        unsubmitted_df = df[~df['uid'].isin(submissions)]

        # Replace NaNs with blank strings
        unsubmitted_df = unsubmitted_df.replace(np.nan, '', regex=True)

        # Optimise candidate selections
        print('* Optimising candidate selections...')
        unsubmitted_df.sort_values(by=['location', 'duration', 'item_count', 'content_dates'],
                                ascending=[False, False, False, True],
                                inplace=False)

        write_to_log(f'{str(unsubmitted_df)}\n')

        batch_items = []
        batch = unsubmitted_df.head(batch_size)

        print('* Check batch_size...')
        if len(batch) != batch_size:
            print(f'* Batch size check results: {len(batch)} != {batch_size}...')
            print('* Therefore quitting...')
            continue

        # Create batch
        print('* Batch size check results: len(batch) = batch_size...')
        print('* Creating batch...')
        for i in batch.iterrows():
            row = i[1]

            # Wrangle data for output
            data = row.tolist()
            submission = [data[2]] + data[0:1] + data[3:]

            # Get item identifiers
            items = submission[-1].split(',')
            prirefs = [workflow.get_priref(i) for i in items]
            batch_items.extend(prirefs)

            # Track submission
            print('* Writing 2inch submissions to twoinch/submissions.csv...')
            with open(os.path.join(TWOINCH, 'submissions.csv'), 'a') as of:
                writer = csv.writer(of)
                writer.writerow(submission)

        # Populate topNode fields
        print('* Creating Workflow topnode metadata...')
        today = datetime.today().strftime('%d-%m-%Y')
        job_metadata = dict(configuration['WorkflowMetadata'])

        # Append date and batch number to title
        q = 'topNode="x" and description="*2inch TVP / Ofcom*" and input.name="collectionssystems"'
        lifetime_batches = workflow.count_jobs_submitted(q) + 1
        job_metadata['description'] = '{} / {} / {}'.format(job_metadata['description'],
                                                            today, lifetime_batches)

        # Calculate deadline
        deadline = (datetime.today() + timedelta(days=10)).strftime('%Y-%m-%d')
        job_metadata['completion.date'] = deadline
        job_metadata['negotiatedDeadline'] = deadline

        # Create Workflow records (will need testing when running records)
        print('* Creating Workflow records in CID...')
        batch = workflow.twoInchBatch(items=batch_items, **job_metadata)
        if not batch.successfully_completed:
            print(batch_items, batch)
            error_row = [str(today), batch.priref, batch.task.job_number, ','.join(batch_items)]

            with open(os.path.join(TWOINCH, 'errors.csv'), 'a') as of:
                writer = csv.writer(of)
                writer.writerow(error_row)

            write_to_log(f'{str(error_row)}\n')
            print(f'Error creating 2inch Workflow job: {batch.priref}')


def write_to_log(message):
    '''
    Write to 2inch submitta log
    '''
    with open(os.path.join(LOGS, '2inch_submitta.log'), 'a') as file:
        file.write(message)
        file.close()


if __name__ == '__main__':
    main()
