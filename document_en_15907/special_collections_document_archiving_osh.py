#!/usr/bin/env python3

'''
Special Collections Document Archiving script for OSH

Script stages:
1. Iterate through supplied sys.argv[1] folder path
2. For each subfolder split folder name: ob_num / ISAD(G) level / Title
3. Create CID record for each folder following level from folder name
   - Only when subfolder starts with object number of parent folder
   - Only creating Series, Sub Series and Sub Sub Series (awaiting record_type for last)
   - For items (any digital document) create an Archive Item record (df='ITEM_ARCH')
4. Join to the parent/children records through the ob_num part/part_of
5. Once at bottom of folders in sub or sub sub series, order files by creation date (if possble)
6. Check for filename already in digital.acquired_filename in CID already (report where found)
7. CID archive item records are to be made for each, and linked to parent folder:
      Named GUR-2-1-1-1-1, GUR-2-1-1-1-2 etc based on parent's object number
      Original filename is to be captured into the Item record digital.acquired_filename
      Rename the file and move to autoingest.

2025
'''

# Public packages
import os
import sys
import shutil
import logging
import datetime
from typing import Optional, Final, List, Dict

# Private packages
sys.path.append(os.environ.get('CODE'))
import adlib_v3_sess as adlib
import utils

# Global path variables
AUTOINGEST = os.path.join(os.environ.get('AUTOINGEST_BP_SC'), 'ingest/autodetect/')
LOG = os.path.join(os.environ.get('LOG_PATH'), 'special_collections_document_archiving_osh.log')
MEDIAINFO_PATH = os.path.join(os.environ.get('LOG_PATH'), 'cid_mediainfo/')
CID_API = os.environ.get('CID_API4')

LOGGER = logging.getLogger('sc_document_archiving_osh')
HDLR = logging.FileHandler(LOG)
FORMATTER = logging.Formatter('%(asctime)s\t%(levelname)s\t%(message)s')
HDLR.setFormatter(FORMATTER)
LOGGER.addHandler(HDLR)
LOGGER.setLevel(logging.INFO)


def cid_retrieve(fname: str, session) -> Optional[tuple[str, str, str]]:
    '''
    Receive filename and search in CID works dB
    Return selected data to main()
    '''
    search: str = f'object_number="{fname}"'
    fields: list[str] = [
        'priref',
        'title',
        'title.article'
    ]

    record = adlib.retrieve_record(CID_API, 'works', search, '1', session, fields)[1]
    LOGGER.info("cid_retrieve(): Making CID query request with:\n%s", search)
    if not record:
        print(f"cid_retrieve(): Unable to retrieve data for {fname}")
        utils.logger(LOG, 'exception', f"cid_retrieve(): Unable to retrieve data for {fname}")
        return None

    if 'priref' in str(record):
        priref = adlib.retrieve_field_name(record[0], 'priref')[0]
    else:
        priref = ""
    if 'Title' in str(record):
        title = adlib.retrieve_field_name(record[0], 'title')[0]
    else:
        title = ""
    if 'title.article' in str(record):
        title_article = adlib.retrieve_field_name(record[0], 'title.article')[0]
    else:
        title_article = ""

    return priref, title, title_article,


def sort_dates(file_list: List[str]) -> List[str]:
    '''
    Get modification date of files, and sort into newest first
    return with enumeration number
    '''
    time_list = []
    for file_path in file_list:
        time = os.path.getmtime(file_path)
        time_list.append(f"{time} - {file_path}")

    time_list.sort()

    enum_list = []
    for i, name in enumerate(time_list):
        enum_list.append(f"{name.split(' - ', 1)[-1]}, {i + 1}")

    return enum_list


def folder_split(fname):
    '''
    Split folder name into parts
    '''
    fsplit = fname.split('_', 2)
    print(fsplit)
    if len(fsplit) != 3:
        LOGGER.warning("Folder has not split as anticipated: %s", fsplit)
        return None, None, None
    ob_num, record_type, title = fsplit
    if not ob_num.startswith(('GUR', '')):
        LOGGER.warning("Object number is not formatted as anticipated: %s", ob_num)
        return None, None, None

    return ob_num, record_type, title


def main():
    '''
    Iterate supplied folder, find image files in folders
    named after work and create analogue/digital item records
    for every photo. Clean up empty folders.
    '''
    if not utils.check_control('power_off_all'):
        LOGGER.info("Script run prevented by downtime_control.json. Script exiting.")
        sys.exit("Script run prevented by downtime_control.json. Script exiting.")
    if not utils.cid_check(CID_API):
        sys.exit("* Cannot establish CID session, exiting script")

    LOGGER.info("=========== Special Collections rename - Document Archiving OSH START ============")

    base_dir = sys.argv[1]  # sub_fond level path
    sub_fond = os.path.basename(base_dir)
    print(base_dir)
    sf_ob_num, sf_record_type, sf_title = folder_split(sub_fond)
    print(f"Sub fond data found: {sf_ob_num}, {sf_record_type}, {sf_title}")
    LOGGER.info("Sub fond data: %s, %s, %s", sf_ob_num, sf_record_type, sf_title)

    if not os.path.isdir(base_dir):
        sys.exit("Folder path is not a valid path")

    series = []
    sub_series = []
    sub_sub_series = []
    sub_sub_sub_series = []
    file = []
    for root, dirs, _ in os.walk(base_dir):
        for directory in dirs:
            if not str(directory).startswith(sf_ob_num):
                continue
            dpath = os.path.join(root, directory)
            if '_series_' in str(directory):
                series.append(dpath)
            elif '_sub-series_' in str(directory):
                sub_series.append(dpath)
            elif '_sub-sub-series_' in str(directory):
                sub_sub_series.append(dpath)
            elif '_sub-sub-sub-series_' in str(directory):
                sub_sub_sub_series.append(dpath)
            elif '_file_' in str(directory):
                file.append(dpath)
            else:
                pass

    print(f"Series: {series}")
    print(f"Sub-series: {sub_series}")
    print(f"Sub-sub-series: {sub_sub_series}")
    print(f"File: {file}")
    '''
    session = adlib.create_session()
    # Only match directories that start with GUR-1 / GUR-2 etc.
    series = [x for x in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, x)) and x.startswith(sf_ob_num)]
    series.sort()
    LOGGER.info("Series found %s: %s", len(series), ', '.join(series))

    LOGGER.info("Targeting %s - %s, title %s", sf_ob_num, sf_record_type, sf_title)
    #sf_priref, title, title_art = cid_retrieve(sf_ob_num, session)
    #LOGGER.info("Matched priref to %s: %s %s %s", sf_ob_num, sf_priref, title_art, title)
    print("**** SERIES PROCESSING ****")
    series_structure_all = []
    series_ob_num = []
    for folder in series:
        fpath = os.path.join(base_dir, folder)
        ob_num, record_type, title = folder_split(folder)
        if ob_num is None:
            continue
        series_ob_num.append(f"New object number: {ob_num} / Parent: {sf_ob_num} / Record type: {record_type} / {title}")
        print(f"New series object number: {ob_num} / Parent: {sf_ob_num} / Record type: {record_type} / {title}")
        series_structure = [os.path.join(fpath, x) for x in os.listdir(fpath) if os.path.isdir(os.path.join(fpath, x)) and x.startswith(ob_num)]
        if series_structure is not None:
            series_structure.sort()
            series_structure_all = series_structure_all + series_structure
    LOGGER.info("Series data retrieved")

    print("**** SUB SERIES PROCESSING ****")
    sub_series_ob_num = []
    sub_series_structure = {}
    folders = []
    files = []
    for fpath in series_structure_all:
        print(fpath)
        sub_path, folder = os.path.split(fpath)
        parent_ob_num = os.path.basename(sub_path).split('_', 1)[0]
        ob_num, record_type, title = folder_split(folder)
        if ob_num is None:
            continue
        sub_series_ob_num.append(f"New object number: {ob_num} / Parent: {parent_ob_num} / Record type: {record_type} / {title}")
        print(f"New sub_series object number: {ob_num} / Parent: {parent_ob_num} / Record type: {record_type} / {title}")
        folders = [f"{os.path.join(fpath, x)}" for x in os.listdir(fpath) if os.path.isdir(os.path.join(fpath, x)) and x.startswith(ob_num)]
        if folders:
            folders.sort()
            sub_series_structure[f"{fpath} folders"] = folders
        files = [f"{os.path.join(fpath, x)}" for x in os.listdir(fpath) if os.path.isfile(f"{os.path.join(fpath, x)}")]
        if files:
            enum_files = sort_dates(files)
            sub_series_structure[f"{fpath} files"] = enum_files

    print("Archive items found in creation date order:")
    for file in sub_series_structure[f"{fpath} files"]:
        print(f"{fpath} files")

    sub_sub_series_structure = {}
    print("**** SUB SUB SERIES PROCESSING ****")
    folders = []
    files = []
    for key, value in sub_series_structure.items():
        if 'sub-sub-series' not in str(key):
            continue
        if ' folders' in key:
            if not value:
                continue
            for fpath in value:
                print(fpath)
                sub_path, folder = os.path.split(fpath)
                parent_ob_num = os.path.basename(sub_path).split('_', 1)[0]
                ob_num, record_type, title = folder_split(folder)
                if ob_num is None:
                    continue
                sub_series_ob_num.append(f"New object number: {ob_num} / Parent: {parent_ob_num} / Record type: {record_type} / {title}")
                print(f"New sub_sub_series object number: {ob_num} / Parent: {parent_ob_num} / Record type: {record_type} / {title}")
                files = [f"{os.path.join(fpath, x)}" for x in os.listdir(fpath) if os.path.isfile(f"{os.path.join(fpath, x)}")]
                if files:
                    enum_files = sort_dates(files)
                    sub_sub_series_structure[f"{fpath}"] = enum_files

    file_structure = {}
    print("**** FILES PROCESSING ****")
    files = []
    for key, value in sub_series_structure.items():
        if ' folders' in key:
            if not value:
                continue
            if 'sub-sub-series' in str(key):
                continue
            for fpath in value:
                print(fpath)
                sub_path, folder = os.path.split(fpath)
                parent_ob_num = os.path.basename(sub_path).split('_', 1)[0]
                ob_num, record_type, title = folder_split(folder)
                if ob_num is None:
                    continue
                sub_series_ob_num.append(f"New object number: {ob_num} / Parent: {parent_ob_num} / Record type: {record_type} / {title}")
                print(f"New sub_sub_series object number: {ob_num} / Parent: {parent_ob_num} / Record type: {record_type} / {title}")
                files = [f"{os.path.join(fpath, x)}" for x in os.listdir(fpath) if os.path.isfile(f"{os.path.join(fpath, x)}")]
                if files:
                    enum_files = sort_dates(files)
                    file_structure[f"{fpath}"] = enum_files
    LOGGER.info("File data retrieved:\n%s", file_structure)


    print("Archive items found in creation date order")
    for k, v in sub_sub_series_structure.items():
        for file in v:
            print(f"\t{file}")
    print("=--------------------------------=")
    print("Archive File items found in creation date order")
    for k, v in file_structure.items():
        for file in v:
            print(f"\t{file}")        

    LOGGER.info("=========== Special Collections - Document Archiving OSH END ==============")
    '''

def create_series(series_dct, parent_priref, parent_ob_num, title_art, title):
    '''
    Receive dict of series data
    and create records for each
    and create CID records
    '''
    dct = {}
    dct.append({'Df': 'SERIES'})
    pass



def create_sub_series(sub_series_dct, parent_priref, parent_ob_num, title_art, title):
    '''
    Receive dict of series data
    and create records for each
    and create CID records
    '''
    dct = {}
    dct.append({'Df': 'SUB_SERIES'})
    pass



def create_sub_sub_series(sub_sub_series_dct, parent_priref, parent_ob_num, title_art, title):
    '''
    Receive dict of series data
    and create records for each
    and create CID records
    This record_type is not yet created!
    '''
    dct = {}
    dct.append({'Df': 'SUB_SUB_SERIES'})
    pass



def create_files(files_dct, parent_priref, parent_ob_num, title_art, title):
    '''
    Receive dict of series data
    and create records for each
    and create CID records
    '''
    dct = {}
    dct.append({'Df': 'FILES'})
    pass


def create_archive_item(ipath, num, parent_priref, parent_ob_num, title):
    '''
    Get data needed for creation of item archive record
    Receive item fpath, enumeration, parent priref/ob num and title
    '''
    root, iname = os.path.split(ipath)
    ext = os.path.splitext(iname)
    ob_num = f"{parent_ob_num}-{num}"
    new_name = f"{ob_num}.{ext}"
    record_dct = {
        'title': title,
        'digital.acquired_filename': iname,
        'object_number': ob_num,
        'Df': 'ITEM_ARCH'
    }



def rename_files(fpath, parent_ob_num, index):
    '''
    Using index and parent object number
    create a new filename and rename fpath
    '''
    pass


def build_defaults(title_art, title) -> Optional[tuple[list[dict[str, str]], Optional[str]]]:
    '''
    Use this function to just build standard defaults for all GUR records
    Discuss what specific record data they want in every record / some records

    records = ([
        {'institution.name.lref': '999570701'},
        {'object_type': 'OBJECT'}
    ])
    print(work_data)
    if work_data[1]:
        records.append({'related_object.reference.lref': work_data[0]})
    else:
        LOGGER.warning("No parent object number retrieved. Script exiting.")
        return None
    if work_data[2]:
        records.append({'title': work_data[2]})
    else:
        LOGGER.warning("No title data retrieved. Script exiting.")
        return None
    if work_data[3]:
        records.append({'title.article': work_data[3]})
    if work_data[4]:
        records.append({'production.date.start': work_data[4]})

    if arg == 'analogue':
        records.append({'analogue_or_digital': 'ANALOGUE'})
    elif arg == 'digital':
        records.append({'analogue_or_digital': 'DIGITAL'})
        records.append({'digital.born_or_derived': 'DIGITAL_DERIVATIVE_PRES'})
        records.append({'digital.acquired_filename': image})
        if obj:
            records.append({'source_item': obj})
        ext = image.split('.')[-1]
        if ext.lower() in ['jpeg', 'jpg']:
            records.append({'file_type.lref': '396310'})
        elif ext.lower() in ['tif', 'tiff']:
            records.append({'file_type.lref': '395395'})

    '''
    records.append({'input.name': 'datadigipres'})
    records.append({'input.date': str(datetime.datetime.now())[:10]})
    records.append({'input.time': str(datetime.datetime.now())[11:19]})
    records.append({'input.notes': 'Automated record creation for Special Collections, to facilitate ingest to DPI'})
    print(records)
    return records


def create_new_record(object_number, record_type, record_dct, session) -> Optional[tuple[str, str]]:
    '''
    Function for creation of new CID records JMW:
    Check if supplying Object Number has any adlib XML requirements!!
    '''
    print(record_dct)
    record_xml = adlib.create_record_data(CID_API, 'archivescatalogue', '', record_json)
    print(record_xml)
    record = adlib.post(CID_API, record_xml, 'archivescatalogue', 'insertrecord', session)
    if not record:
        LOGGER.warning("Adlib POST failed to create CID item record for data:\n%s", record_xml)
        return None

    priref = adlib.retrieve_field_name(record, 'priref')[0]
    obj = adlib.retrieve_field_name(record, 'object_number')[0]
    return priref, obj


def update_acquired_filename(priref, acquired_filename, session):
    '''
    Update the file's original filename
    to digital.acquired_filename field
    using new item record priref
    '''
    payload_head: str = f"<adlibXML><recordList><record priref='{priref}'>"
    payload_mid: str = f"<digital.acquired_filename>'{acquired_filename}</digital.acquired_filename>"
    payload_end: str = "</record></recordList></adlibXML>"
    payload: str = payload_head + payload_mid + payload_end

    record = adlib.post(CID_API, payload, 'archivescatalogue', 'updaterecord', session)
    if record is None:
        return False
    elif 'error' in str(record):
        return False
    else:
        return True


def rename(filepath: str, ob_num: str) -> tuple[str, str]:
    '''
    Receive original file path and rename filename - TBU
    based on object number, return new filepath, filename
    '''
    new_filepath, new_filename = '', ''
    ipath, filename = os.path.split(filepath)
    ext = os.path.splitext(filename)[1]
    new_name = ob_num.replace('-', '_')
    new_filename = f"{new_name}_01of01{ext}"
    print(f"Renaming {filename} to {new_filename}")
    new_filepath = os.path.join(ipath, new_filename)

    try:
        os.rename(filepath, new_filepath)
    except OSError:
        LOGGER.warning("There was an error renaming %s to %s", filename, new_filename)

    return (new_filepath, new_filename)


def move(filepath: str, arg: str) -> bool:
    '''
    Move existing filepaths to Autoingest - TBU
    '''
    if os.path.exists(filepath) and 'fail' in arg:
        pth: str = os.path.split(filepath)[0]
        failures: str = os.path.join(pth, 'failures/')
        os.makedirs(failures, mode=0o777, exist_ok=True)
        print(f"move(): Moving {filepath} to {failures}")
        try:
            shutil.move(filepath, failures)
            return True
        except Exception as err:
            LOGGER.warning("Error trying to move file %s to %s. Error %s", filepath, failures, err)
            return False
    elif os.path.exists(filepath) and 'ingest' in arg:
        print(f"move(): Moving {filepath} to {AUTOINGEST}")
        try:
            shutil.move(filepath, AUTOINGEST)
            return True
        except Exception:
            LOGGER.warning("Error trying to move file %s to %s", filepath, AUTOINGEST)
            return False
    else:
        return False


if __name__ == '__main__':
    main()
