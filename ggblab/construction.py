import base64
import zipfile
import json
import xml.etree.ElementTree as ET
import io
import os

from .schema import ggb_schema

class ggb_construction:
    """GeoGebra construction file (.ggb) loader and saver.
    
    Handles multiple file formats:
    - .ggb files (base64-encoded ZIP archives)
    - Plain ZIP archives
    - JSON format
    - Plain XML (geogebra.xml)
    
    The loader automatically detects file type from magic bytes and extracts
    the construction XML. The geogebra_xml is automatically stripped to the
    <construction> element and scientific notation is normalized.
    
    Attributes:
        ggb_schema: XML schema for validation
        source_file (str): Path to the loaded file
        base64_buffer (bytes): Base64-encoded .ggb archive (if applicable)
        geogebra_xml (str): Extracted construction XML
    
    Example:
        >>> construction = ggb_construction()
        >>> construction.load('myfile.ggb')
        >>> construction.save('output.ggb')
    """
    def __init__(self):
        self.ggb_schema = ggb_schema().schema
    
    def load(self, file):
        """Load a GeoGebra construction from file.
        
        Supports multiple formats:
        - Base64-encoded .ggb (starts with 'UEsD')
        - ZIP archive (starts with 'PK')
        - JSON format (starts with '{' or '[')
        - Plain XML
        
        The construction XML is automatically extracted and normalized:
        - Stripped to <construction> element only
        - Scientific notation fixed (e-1 → E-1)
        
        Args:
            file (str): Path to the .ggb, .zip, .json, or .xml file.
        
        Returns:
            ggb_construction: Self reference for method chaining.
            
        Raises:
            FileNotFoundError: If the file does not exist.
            RuntimeError: If file loading fails.
            
        Example:
            >>> c = ggb_construction().load('circle.ggb')
            >>> print(c.geogebra_xml[:100])
        """
        self.source_file = file

        self.base64_buffer = None
        self.geogebra_xml = None

        try:
            with open(self.source_file, 'rb') as f:
                def unzip(buff):
                    with zipfile.ZipFile(io.BytesIO(base64.b64decode(buff)), 'r') as zf:
                        # for fileinfo in zf.infolist():
                        #     print(fileinfo)
                        with zf.open('geogebra.xml', 'r') as zff:
                            try:
                                s = zff.read()
                            except:
                                pass
                    return s

                match tuple(f.read(4).decode()):
                    case ('U', 'E', 's', 'D'):
                        # base64 encoded zip
                        f.close()
                        with open(self.source_file, 'rb') as f2:
                            self.base64_buffer = f2.read()  # base64.b64decode(f2.read())
                            self.geogebra_xml = unzip(self.base64_buffer)
                    case ('P', 'K', _, _):
                        # zip
                        f.close()
                        with open(self.source_file, 'rb') as f2:
                            # b64encode for sending GeoGebra Applet
                            self.base64_buffer = base64.b64encode(f2.read())
                            self.geogebra_xml = unzip(self.base64_buffer)
                    case ('{', _, _, _) | ('[', _, _, _):
                        # json
                        f.close()
                        with open(self.source_file, 'r', encoding='utf-8') as f2:
                            self.base64_buffer = json.load(f2)
                            for f in self.base64_buffer['archive']:
                                if f['fileName'] == 'geogebra.xml':
                                    self.geogebra_xml = f['fileContent']
                    case _:
                        # xml?
                        with open(self.source_file, 'r', encoding='utf-8') as f2:
                            self.geogebra_xml = f2.read()
            # return self.initialize_dataframe(file)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {self.source_file}")
        except Exception as e:
            raise RuntimeError(f"Failed to load the file: {e}")

        # strip to construction element and fix scientific notation
        self.geogebra_xml = (ET.tostring(ET.fromstring(self.geogebra_xml)
                                        .find('./construction'), encoding='unicode')
                            .replace('e-1', 'E-1'))

        return self
    
    def save(self, overwrite=False, file=None):
        """Save the construction to a file.
        
        Saving behavior:
        - If base64_buffer is set: writes decoded archive (.ggb format)
        - If base64_buffer is None: writes plain XML (geogebra_xml)
        - Target extension does not enforce format (e.g., saving to .ggb with
          no base64_buffer will write plain XML bytes)
        
        Args:
            overwrite (bool): If True, overwrite source_file. Defaults to False.
            file (str, optional): Target file path. If None, auto-generates
                next available filename (name_1.ggb, name_2.ggb, ...).
        
        Returns:
            ggb_construction: Self reference for method chaining.
            
        Example:
            >>> c = ggb_construction().load('circle.ggb')
            >>> c.save()  # Saves to circle_1.ggb
            >>> c.save(overwrite=True)  # Overwrites circle.ggb
            >>> c.save(file='output.ggb')  # Saves to output.ggb
        
        Note:
            getBase64() from the applet may not include non-XML artifacts
            (thumbnails, etc.) from the original archive. Saving after API
            changes produces a leaner .ggb file.
        """

        def get_next_revised_filename(filename):
            """
            Generates the next available non-existing filename by appending 
            '_1', '_2', etc. before the file extension.
            """
            if not os.path.exists(filename):
                return filename

            root, ext = os.path.splitext(filename)
            i = 1
            new_filename = f"{root}_{i}{ext}"
            
            while os.path.exists(new_filename):
                i += 1
                new_filename = f"{root}_{i}{ext}"
                
            return new_filename

        if file is None:
            if overwrite:
                file = self.source_file
            else:
                file = get_next_revised_filename(self.source_file)

        with open(file, 'wb') as f:
            if self.base64_buffer is not None:
                f.write(base64.b64decode(self.base64_buffer))
            else:
                f.write(self.geogebra_xml.encode('utf-8'))
        return self