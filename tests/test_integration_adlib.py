import os
import sys

sys.path.append(os.environ["CODE"])
import adlib_v3 as adlib

def test_check():
    api_url = "http://212.114.101.119/CIDDataTest/wwwopac.ashx"
    result = adlib.check(api_url)

    assert "adlibJSON" in result
    assert "version" in result["adlibJSON"]['recordList']['record'][0]

def test_get():

    api_url = "http://212.114.101.119/CIDDataTest/wwwopac.ashx"
    query =  {
        "database": 'items',
        "search": f'(record_type=ITEM) and input.date="2025-10-01"',
        "limit": 1,
        "output": "jsonv1",
    }

    result = adlib.get(api_url, query)

    assert isinstance(result, dict)
    assert "adlibJSON" in result
    assert "file_type" in result["adlibJSON"]['recordList']['record'][0]


def test_get_manifestation():
    api_url = "http://212.114.101.119/CIDDataTest/wwwopac.ashx"
    query =  {
        "database": 'items',
        "search": f'(record_type=MANIFESTATION) and input.date="2025-10-01"',
        "limit": 1,
        "output": "jsonv1",
    }

    result = adlib.get(api_url, query)

    assert isinstance(result, dict)
    assert "adlibJSON" in result
    assert "broadcast_channel" in result["adlibJSON"]['recordList']['record'][0]
    assert "input.notes" in result["adlibJSON"]['recordList']['record'][0]

def test_get_work():
    api_url = "http://212.114.101.119/CIDDataTest/wwwopac.ashx"
    query =  {
        "database": 'works',
        "search": f'(record_type=WORK) and input.date="2025-10-01"',
        "limit": 1,
        "output": "jsonv1",
    }

    result = adlib.get(api_url, query)

    assert isinstance(result, dict)
    assert "adlibJSON" in result
    assert "grouping.lref" in result["adlibJSON"]['recordList']['record'][0]
    assert "input.notes" in result["adlibJSON"]['recordList']['record'][0]
    assert result["adlibJSON"]['recordList']['record'][0]['Title_date'][0]['title_date_start'][0]['spans'][0]['text'] == '2025-09-25'

def test_get_item():
    api_url = "http://212.114.101.119/CIDDataTest/wwwopac.ashx"
    query =  {
        "database": 'items',
        "search": f'(record_type=ITEM) and input.date="2025-10-01"',
        "limit": 1,
        "output": "jsonv1",
    }

    result = adlib.get(api_url, query)

    assert isinstance(result, dict)
    assert "adlibJSON" in result
    # assert "broadcast_company" in result["@attributes"]['recordList']['record'][0]
    assert "input.notes" in result["adlibJSON"]['recordList']['record'][0]

def test_post():
    api_url = "http://212.114.101.119/CIDDataRestricted/wwwopac.ashx"

    # Example payload for updating a record
    payload = "<adlibXML><recordList><record priref='170000006'><quality_comments><quality_comments><![CDATA[TAR file contains: moooooo]]></quality_comments><quality_comments.date>2025-12-04</quality_comments.date><quality_comments.writer>datadigipres</quality_comments.writer></quality_comments></record></recordList></adlibXML>"

    print(adlib.post(api_url, payload, "manifestations", "insertrecord"))

    query =  {
        "database": 'items',
        "search": f"priref='12345'",
        "limit": 1,
        "output": "jsonv1",
    }

    result = adlib.get(api_url, query)
    assert isinstance(result, dict)
