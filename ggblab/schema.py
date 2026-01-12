import requests
import os
import xmlschema
import io
# from pprint import pprint

class ggb_schema:
    url = 'http://www.geogebra.org/apps/xsd/common.xsd'
    local_path = 'xsd/common.xsd'

    def __init__(self):
        # Ensure the cache directory exists
        os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
        self.schema_content = cache_schema_locally(self.url, self.local_path)

        # Assuming you have a geogebra.xml file (from an unzipped .ggb file)
        # and the XSD files (ggb.xsd and common.xsd) downloaded locally
        # or you can use the URL for the schema

        # Create a schema instance (it automatically handles imported common.xsd)
        try:
            self.schema = xmlschema.XMLSchema(io.StringIO(self.schema_content))

            # Convert the XML data to a Python dictionary
            # data_dict = ggb_schema.to_dict(io.StringIO(r))

            # Pretty print the resulting dictionary
            # pprint(data_dict)

        except xmlschema.validators.exceptions.XMLSchemaValidationError as e:
            print(f"XML validation error: {e}")
        except Exception as e:
            print(f"An error occurred: {e}")


def cache_schema_locally(schema_url, local_file_path):
    """
    Downloads a schema from a URL and caches it in a local file.
    If the file already exists, it uses the local copy.
    You might add logic to check file age or a "Last-Modified" header for updates.
    """
    if os.path.exists(local_file_path):
        print(f"Using local cached file: {local_file_path}")
        with open(local_file_path, 'r', encoding='utf-8') as f:
            return f.read()

    print(f"Local file not found. Downloading from: {schema_url}")
    try:
        response = requests.get(schema_url)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Save the content to the local file
        with open(local_file_path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"Successfully downloaded and saved to: {local_file_path}")
        return response.text

    except requests.exceptions.RequestException as e:
        print(f"Error downloading schema: {e}")
        return None