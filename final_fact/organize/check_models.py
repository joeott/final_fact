from google import genai
import os

PROJECT_ID = "document-processor-v3"
LOCATION = "us-central1"

try:
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    print("List of models (filtering for 'gemini'):")
    # Pager for list_models might be needed if many models
    for model in client.models.list(config={"page_size": 100}):
        if "gemini" in model.name.lower():
            print(f"Name: {model.name}")
            print(f"  Resource Name: {model.state_name if hasattr(model, 'state_name') else 'N/A'}")
            # print(f"  Version: {model.version}")

except Exception as e:
    print(f"Error: {e}")
