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

from cldfcatalog.config import Config

from collections import defaultdict
from tqdm import tqdm as progressbar



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

    text = unicodedata.normalize("NFD", text)

    if len(text) >= 1:
        if text[0] == "'" and text[-1] == "'":
            text = text[1:-1]

    return text


class Dataset(BaseDataset):
    dir = Path(__file__).parent
    id = "lapsyd"

    #def cldf_specs(self):  # A dataset must declare all CLDF sets it creates.
    #    return CLDFSpec(dir=self.cldf_dir, module="StructureDataset")

    def cmd_download(self, args):
        """
        Download files to the raw/ directory. You can use helpers methods of `self.raw_dir`, e.g.

        >>> self.raw_dir.download(url, fname)
        """

        pass
        
    def cldf_specs(self):
        return CLDFSpec(
                module='StructureDataset',
                dir=self.cldf_dir,
                data_fnames={'ParameterTable': 'features.csv'}
            )

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
        # +++ check cldf catalog +++ TODO
        clts = CLTS(Config.from_file().get_clone('clts'))
        bipa = clts.bipa

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
            "Value_in_Source"
        )
        args.writer.cldf.add_columns(
                    'ParameterTable',
                    {'name': 'CLTS_BIPA', 'datatype': 'string'},
                    {'name': 'CLTS_Name', 'datatype': 'string'},
                    {'name': 'LAPSYD_Features', 'datatype': 'string'},
                    )
        args.writer.cldf.add_component(
            "LanguageTable", "Family", "Glottolog_Name"
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


        languoids = {}
        all_glottolog = {l.id: l for l in glottolog.languoids()}
        for lang, gcode in progressbar(languages.items()):
            language = all_glottolog.get(gcode)
            if language:
                languoids[lang] = {
                        'Family': language.family.name if language.family else '',
                        'Glottocode': gcode,
                        'Name': lang,
                        'ID': lang_ids[gcode],
                        'ISO630P3code': language.iso_code,
                        'Macroarea': language.macroareas[0].name if language.macroareas else '',
                        'Latitude': language.latitude,
                        'Longitude': language.longitude,
                        'Glottolog_Name': language.name
                        }
            else:
                languoids[lang] = {
                        'ID': lang_ids[gcode],
                        'Name': lang
                        }


        # Iterate over raw data
        values = []
        segments = []
        unknowns = defaultdict(list)
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

            # Due to the behavior of `.resolve_grapheme`, we need to attempt,
            # paying attention to raised exceptions, to convert in different ways
            # +++ TODO +++ fix the problem of bipa graphemes here
            lapsyd_clts = clts.transcriptiondata_dict['lapsyd']
            if normalized in lapsyd_clts.grapheme_map:
                sound = bipa[lapsyd_clts.grapheme_map[normalized]]
            else:
                sound = bipa['<NA>']
                unknowns[normalized] += [(segment, language)]

            par_id = compute_id(normalized)
            if sound.type == 'unknownsound':
                bipa_grapheme = ''
                desc = ''
            else:
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
                    "Value_in_Source": segment,
                    "Value": normalized,
                    "Source": lang_sources[languages[row["name"]]],
                    "Catalog": "lapsyd",
                }
            )

        # Build parameter data, extending with Lapsyd Features
        parameters = []
        for segment in set(segments):
            ID, normalized, bipa_grapheme, desc = segment

            parameter = {
                "ID": ID,
                "Name": normalized,
                "Description": ' '.join(lapsyd_graphemes[normalized]),
                "CLTS_BIPA": bipa_grapheme,
                "CLTS_Name": desc,
                "LAPSYD_Features": ' '.join(lapsyd_graphemes[normalized])
            }

            parameters.append(parameter)

        # Write data and validate
        args.writer.write(
            **{
                "ValueTable": values,
                "LanguageTable": languoids.values(),
                "ParameterTable": parameters
            }
        )

        for g, rest in unknowns.items():
            print('\t'.join([g, str(len(rest)), g, ' '.join(lapsyd_graphemes[g])]))
