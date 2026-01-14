import requests
import os
import xmlschema
import io
# from pprint import pprint

class ggb_schema:
    """GeoGebra XML schema loader and validator.
    
    Manages the GeoGebra XML schema (XSD) for validating and parsing .ggb
    construction files. The schema is automatically downloaded from the
    official GeoGebra site and cached locally for offline use.
    
    The schema enables:
    - XML validation of GeoGebra constructions
    - Conversion between XML and Python dictionaries
    - Type-safe parsing of construction elements
    
    Attributes:
        url (str): URL of the GeoGebra common.xsd schema file
        local_path (str): Local cache path for the downloaded schema
        schema_content (str): Raw XSD content as string
        schema (xmlschema.XMLSchema): Compiled schema object for validation
    
    Example:
        >>> schema = ggb_schema()
        >>> # Schema is loaded and ready for use
        >>> data_dict = schema.schema.to_dict(xml_string)
    
    Note:
        The schema is downloaded once and cached in xsd/common.xsd.
        Delete the cache to force re-download on next instantiation.
    """
    url = 'http://www.geogebra.org/apps/xsd/common.xsd'
    local_path = 'xsd/common.xsd'

    def __init__(self):
        """Initialize the schema loader and load/cache the XSD file.
        
        Downloads the GeoGebra schema from the official URL if not already
        cached locally. Creates the cache directory if it doesn't exist.
        
        Raises:
            xmlschema.validators.exceptions.XMLSchemaValidationError: If schema is invalid.
            Exception: If schema download or loading fails.
        """
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
    """Download and cache a schema file from URL.
    
    Downloads an XML schema from the specified URL and saves it to a local
    file for offline use. If the file already exists, uses the cached version
    instead of re-downloading.
    
    Args:
        schema_url (str): URL of the schema file to download.
        local_file_path (str): Path where the schema should be cached.
    
    Returns:
        str: Content of the schema file, or None if download fails.
    
    Examples:
        >>> content = cache_schema_locally(
        ...     'http://example.com/schema.xsd',
        ...     'cache/schema.xsd'
        ... )
        Using local cached file: cache/schema.xsd
    
    Note:
        Future enhancement: Add logic to check file age or Last-Modified
        header to refresh stale cached schemas.
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