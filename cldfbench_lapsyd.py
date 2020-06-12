from collections import OrderedDict
import pathlib
from unidecode import unidecode
import unicodedata

from cldfbench import CLDFSpec
from cldfbench import Dataset as BaseDataset
from clldutils.misc import slug
from clldutils.path import git_describe

# TODO: temporary instantiation of catalogs
import pyglottolog

GLOTTOLOG_PATH = "/home/tresoldi/.config/cldf/glottolog"
GLOTTOLOG = pyglottolog.Glottolog(GLOTTOLOG_PATH)


def compute_id(text):
    """
    Returns a codepoint representation to an Unicode string.
    """

    unicode_repr = ["U{0:0{1}X}".format(ord(char), 4) for char in text]

    return "%s_%s" % ("_".join(unicode_repr), unidecode(text))


class Dataset(BaseDataset):
    dir = pathlib.Path(__file__).parent
    id = "lapsyd"

    def cldf_specs(self):  # A dataset must declare all CLDF sets it creates.
        return CLDFSpec(dir=self.cldf_dir, module="StructureDataset")

    def cmd_download(self, args):
        """
        Download files to the raw/ directory. You can use helpers methods of `self.raw_dir`, e.g.

        >>> self.raw_dir.download(url, fname)
        """
        pass

    def cmd_makecldf(self, args):
        """
        Convert the raw data to a CLDF dataset.

        >>> args.writer.objects['LanguageTable'].append(...)
        """

        # Extract BIPA features and glottolog version
        glottolog_version = git_describe(GLOTTOLOG.repos)

        # Add components
        args.writer.cldf.tablegroup.notes.append(
            OrderedDict(
                [
                    ("dc:title", "environment"),
                    (
                        "properties",
                        OrderedDict([("glottolog_version", glottolog_version)]),
                    ),
                ]
            )
        )
        args.writer.cldf.add_columns(
            "ValueTable",
            {"name": "Marginal", "datatype": "boolean"},
            {"name": "Allophones", "separator": " "},
            "Contribution_ID",
        )

        args.writer.cldf.add_component("ParameterTable")
        args.writer.cldf.add_component(
            "LanguageTable", "Family_Glottocode", "Family_Name"
        )
        args.writer.cldf.add_table(
            "inventories.csv",
            "ID",
            "Name",
            "Contributor_ID",
            {
                "name": "Source",
                "propertyUrl": "http://cldf.clld.org/v1.0/terms.rdf#source",
                "separator": ";",
            },
            "URL",
            "Tones",
            primaryKey="ID",
        )

        # load language mapping and build inventory info
        languages = []
        inventories = []
        glottocodes = {}
        for row in self.etc_dir.read_csv("languages.csv", dicts=True):
            # extend language info
            languages.append(row)

            # Add mapping, if any
            if row["glottocode"]:
                glottocodes[row["name"]] = row["glottocode"]

            # collect inventory info
            inventories.append(
                {
                    "Contributor_ID": None,
                    "ID": slug(row["name"]),
                    "Name": row["name"],
                    "Source": [],
                    "URL": None,
                    "Tones": None,
                }
            )

        # Map glottolog from etc/languages.csv
        languoids = {
            lang.id: {
                "Family_Glottocode": lang.lineage[0][1] if lang.lineage else None,
                "Family_Name": lang.lineage[0][0] if lang.lineage else None,
                "Glottocode": lang.id,
                "ID": lang.id,
                "ISO639P3code": lang.iso_code,
                "Latitude": lang.latitude,
                "Longitude": lang.longitude,
                "Macroarea": lang.macroareas[0].name if lang.macroareas else None,
                "Name": lang.name,
            }
            for lang in GLOTTOLOG.languoids()
            if lang.id in glottocodes.values()
        }

        # Iterate over raw data
        segment_set = set()
        values = []
        counter = 1
        for idx, row in enumerate(self.raw_dir.read_csv("lapsyd.csv", dicts=True)):
            # clear segment data
            segment = row["segments"].strip()
            if not segment:
                continue

            if segment[0] == "'":
                segment = segment[1:-1]
                marginal = True
            else:
                marginal = False

            segment_set.add(segment)

            values.append(
                {
                    "ID": str(idx + 1),
                    "Language_ID": glottocodes[row["name"]],
                    "Marginal": marginal,
                    "Parameter_ID": compute_id(segment),  # Compute
                    "Value": segment,
                    "Source": [],  # TODO
                }
            )

        # Build segment data
        segments = [
            {"Name": unicodedata.normalize("NFC", segment), "ID": compute_id(segment)}
            for segment in segment_set
        ]

        # Write data and validate
        args.writer.write(
            **{
                "ValueTable": values,
                "LanguageTable": languoids.values(),
                "ParameterTable": segments,
                "inventories.csv": inventories,
            }
        )
