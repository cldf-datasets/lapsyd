from collections import OrderedDict
from pathlib import Path
from unidecode import unidecode
import unicodedata

from cldfbench import CLDFSpec
from cldfbench import Dataset as BaseDataset
from clldutils.misc import slug
from clldutils.path import git_describe

from pyglottolog import Glottolog
from pyclts import CLTS, models
from pycldf import Sources


def compute_id(text):
    """
    Returns a codepoint representation to an Unicode string.
    """

    unicode_repr = "".join(["u{0:0{1}X}".format(ord(char), 4) for char in text])

    label = slug(unidecode(text))

    return "%s_%s" % (label, unicode_repr)


def normalize_grapheme(text):
    """
    Apply simple, non-CLTS, normalization.
    """

    text = unicodedata.normalize("NFC", text)

    if len(text) >= 1:
        if text[0] == "'" and text[-1] == "'":
            text = text[1:-1]

    return text


class Dataset(BaseDataset):
    dir = Path(__file__).parent
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

        # Add sources
        sources = Sources.from_file(self.raw_dir / "sources.bib")
        args.writer.cldf.add_sources(*sources)

        # Instantiate Glottolog and CLTS
        # TODO: how to call CLTS?
        glottolog = Glottolog(args.glottolog.dir)
        clts_path = Path.home() / ".config" / "cldf" / "clts"
        clts = CLTS(clts_path)

        # Load Lapsyd feature mapping and features
        lapsyd_graphemes = {}
        lapsyd_features = set()
        for row in self.etc_dir.read_csv("features.tsv", delimiter="\t", dicts=True):
            # Features will be checked against the normalized grapheme
            grapheme = normalize_grapheme(row["Grapheme"])

            grapheme_features = row["Name"].split()
            lapsyd_graphemes[grapheme] = grapheme_features
            lapsyd_features.update(grapheme_features)

        # Add components
        args.writer.cldf.add_columns(
            "ValueTable",
            {"name": "Marginal", "datatype": "boolean"},
            "Catalog",
            "Contribution_ID",
        )

        args.writer.cldf.add_component(
            "ParameterTable", "BIPA", *[slug(feature) for feature in lapsyd_features]
        )

        args.writer.cldf.add_component(
            "LanguageTable", "Family_Glottocode", "Family_Name", "Glottolog_Name"
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
        languages = {}
        lang_ids = {}
        lang_sources = {}
        inventories = []
        for row in self.etc_dir.read_csv("languages.csv", dicts=True):
            # Build language mapping
            languages[row["name"]] = row["glottocode"]
            lang_ids[row["glottocode"]] = f"{slug(row['name'])}_{row['glottocode']}"
            lang_sources[row["glottocode"]] = row["sources"].split(",")

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
        # TODO: report original name as well
        languoids = {
            lang.id: {
                "Family_Glottocode": lang.lineage[0][1] if lang.lineage else None,
                "Family_Name": lang.lineage[0][0] if lang.lineage else None,
                "Glottocode": lang.id,
                "ID": lang_ids[lang.id],  # lang.id,
                "ISO639P3code": lang.iso_code,
                "Latitude": lang.latitude,
                "Longitude": lang.longitude,
                "Macroarea": lang.macroareas[0].name if lang.macroareas else None,
                "Name": lang.name,
                "Glottolog_Name": lang.name,
            }
            for lang in glottolog.languoids()
            if lang.id in languages.values()
        }

        # Iterate over raw data
        values = []
        segments = []
        for idx, row in enumerate(self.raw_dir.read_csv("lapsyd.csv", dicts=True)):
            # clear segment data
            segment = row["segments"].strip()
            if not segment:
                continue

            # marginal sound?
            if len(segment) > 1 and segment[0] == "'":
                marginal = True
            else:
                marginal = False

            # Obtain the corresponding BIPA grapheme, is possible
            normalized = normalize_grapheme(segment)
            sound = clts.bipa[normalized]
            if isinstance(sound, models.UnknownSound):
                par_id = "UNK_" + compute_id(normalized)
                bipa_grapheme = ""
                desc = ""
            else:
                par_id = "BIPA_" + compute_id(normalized)
                bipa_grapheme = str(sound)
                desc = sound.name
            segments.append((par_id, normalized, bipa_grapheme, desc))

            values.append(
                {
                    "ID": str(idx + 1),
                    "Language_ID": lang_ids[languages[row["name"]]],
                    "Contribution_ID": slug(row["name"]),
                    "Marginal": marginal,
                    "Parameter_ID": par_id,
                    "Value": segment,
                    "Source": lang_sources[languages[row["name"]]],
                    "Catalog": "lapsyd",
                }
            )

        # Build parameter data, extending with Lapsyd Features
        parameters = []
        for segment in set(segments):
            id, normalized, bipa_grapheme, desc = segment

            parameter = {
                "ID": id,
                "Name": normalized,
                "BIPA": bipa_grapheme,
                "Description": desc,
            }

            for feature in lapsyd_features:
                if feature in lapsyd_graphemes[normalized]:
                    parameter[slug(feature)] = "+"
                else:
                    parameter[slug(feature)] = "-"
            parameters.append(parameter)

        # Write data and validate
        args.writer.write(
            **{
                "ValueTable": values,
                "LanguageTable": languoids.values(),
                "ParameterTable": parameters,
                "inventories.csv": inventories,
            }
        )
