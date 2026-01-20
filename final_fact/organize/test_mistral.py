import google.auth
from google.auth.transport.requests import Request
import requests
import json
import base64
import os

PROJECT_ID = "document-processor-v3"
LOCATION = "us-central1"
MODEL_ID = "mistral-ocr-2505"
ENDPOINT = f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/mistralai/models/{MODEL_ID}:rawPredict"

def get_token():
    creds, project = google.auth.default()
    creds.refresh(Request())
    return creds.token

def test_predict():
    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Load a real file to test
    file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "Trial/1. Plaintiff Evidence/Petition.pdf")
    
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, "rb") as f:
        file_content = f.read()
    
    encoded_content = base64.b64encode(file_content).decode('utf-8')
    
    payload = {
        "model": MODEL_ID,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{encoded_content}"
        },
        "include_image_base64": False
    }
    
    print(f"Posting to {ENDPOINT}...")
    response = requests.post(ENDPOINT, headers=headers, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Response Preview: {response.text[:500]}...") # Print first 500 chars to see structure
    
    if response.status_code == 200:
        try:
            print("\nFull Response Keys:", response.json().keys())
        except:
            pass

if __name__ == "__main__":
    test_predict()
