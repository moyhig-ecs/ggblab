import base64
import zipfile
import json
import xml.etree.ElementTree as ET
import io
import os

from .schema import ggb_schema

class ggb_construction:
    def __init__(self):
        self.ggb_schema = ggb_schema().schema
    
    def load(self, file):
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