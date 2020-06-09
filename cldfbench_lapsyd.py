# **NOTE**: While this script is named `cldfbench_eurasianinventories.py`,
#           it is not integrated with `cldfbench` yet; the name is only
#           here as a placeholder for future integration.

from collections import OrderedDict, defaultdict
from pathlib import Path
import base64
import csv
import hashlib
import json
import logging

# Import MPI-SHH libraries
from clldutils.path import git_describe
from pycldf import StructureDataset
from pyglottolog import Glottolog
import pyclts

# BIPA features for descriptors
BIPA_FEATURES = [
    "advanced",
    "affricate",
    "alveolar",
    "alveolo_palatal",
    "apical",
    "approximant",
    "aspirated",
    "back",
    "bilabial",
    "breathy",
    "central",
    "centralized",
    "close",
    "close_mid",
    "cluster",
    "consonant",
    "creaky",
    "dental",
    "devoiced",
    "diphthong",
    "ejective",
    "epiglottal",
    "fricative",
    "front",
    "glottal",
    "glottalized",
    "implosive",
    "labialized",
    "labio_dental",
    "labio_palatal",
    "labio_velar",
    "laminal",
    "lateral",
    "less_rounded",
    "long",
    "lowered",
    "mid",
    "mid_centralized",
    "mid_long",
    "more_rounded",
    "nasal",
    "nasalized",
    "near_back",
    "near_close",
    "near_front",
    "near_open",
    "non_syllabic",
    "open",
    "open_mid",
    "palatal",
    "palatal_velar",
    "palatalized",
    "pharyngeal",
    "pharyngealized",
    "post_alveolar",
    "pre_aspirated",
    "pre_glottalized",
    "pre_labialized",
    "pre_nasalized",
    "raised",
    "retracted",
    "retroflex",
    "rhotacized",
    "rounded",
    "sibilant",
    "stop",
    "syllabic",
    "tap",
    "trill",
    "ultra_long",
    "ultra_short",
    "unrounded",
    "uvular",
    "velar",
    "velarized",
    "voiced",
    "voiceless",
    "vowel",
    "with_frication",
]


def prepare_cldf(glottolog):
    cldf_dir = Path("cldf")

    ds = StructureDataset.in_dir(cldf_dir)
    ds.tablegroup.notes.append(
        OrderedDict(
            [
                ("dc:title", "environment"),
                (
                    "properties",
                    OrderedDict([("glottolog_version", git_describe(glottolog.repos))]),
                ),
            ]
        )
    )
    ds.add_columns(
        "ValueTable",
        {"name": "Marginal", "datatype": "boolean"},
        {"name": "Allophones", "separator": " "},
        "Contribution_ID",
    )

    ds.add_component("ParameterTable", "SegmentClass", *BIPA_FEATURES)
    ds.add_component("LanguageTable", "Family_Glottocode", "Family_Name")
    ds.add_table(
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

    return ds


# Compute the hash/id for a segment
def compute_id(segment):
    return str(base64.b16encode(hashlib.md5(segment.encode("utf-8")).digest()), "utf-8")


def build_segment_data(segment_set, clts):
    # Build segment data
    segments = []
    for segment in segment_set:
        # Initialize all features to negative, and then set as positive
        row = {feature: "-" for feature in BIPA_FEATURES}
        if not isinstance(clts.bipa[segment], pyclts.models.UnknownSound):
            for feature in clts.bipa[segment].featureset:
                row[feature.replace("-", "_")] = "+"

        # Add other info
        if row["vowel"]:
            row["SegmentClass"] = "Vowel"
        elif row["consonant"]:
            row["SegmentClass"] = "Consonant"
        elif row["diphthong"]:
            row["SegmentClass"] = "Diphthong"
        else:
            row["SegmentClass"] = "UnknownSound"

        if not isinstance(clts.bipa[segment], pyclts.models.UnknownSound):
            row["Description"] = clts.bipa[segment].name
        else:
            row["Description"] = None
        row["Name"] = segment
        row["ID"] = compute_id(segment)

        # Update data
        segments.append(row)

    return segments


def main(clts_path, glottolog_path):
    # read raw data
    raw_data_csv = Path("raw") / "lapsyd.csv"
    with open(raw_data_csv.as_posix()) as csvfile:
        raw_data = [row for row in csv.DictReader(csvfile)]

    # Load language mapping
    languages_csv = Path("etc") / "languages.csv"
    with open(languages_csv.as_posix()) as csvfile:
        languages = [row for row in csv.DictReader(csvfile)]
        glottocodes = {
            language["name"]: language["glottocode"]
            for language in languages
            if language["glottocode"]
        }

    inventories = []
    for idx, language in enumerate(languages):
        # Collect inventory info
        inventories.append(
            {
                "Contributor_ID": None,
                "ID": idx + 1,
                "Name": language,
                "Source": [],
                "URL": None,
                "Tones": None,
            }
        )

    # Instantiate CLTS and Glottolog
    clts = pyclts.CLTS(clts_path)
    glottolog = Glottolog(glottolog_path)

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
        for lang in glottolog.languoids()
        if lang.id in glottocodes.values()
    }

    # Prepare dataset
    ds = prepare_cldf(glottolog)

    # Iterate over all entries
    segment_set = set()
    values = []
    counter = 1
    for row in raw_data:
        # clear segment data
        segment = row['segments'].strip()
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
                    "ID": str(counter),
                    "Language_ID": glottocodes[row['name']],
                    "Marginal": marginal,
                    "Parameter_ID": compute_id(segment),  # Compute
                    "Value": segment,
                    "Source": [],  # TODO
                }
            )
        counter += 1

    # Build segment data
    segments = build_segment_data(segment_set, clts)

    # Write data and validate
    ds.write(
        **{
            "ValueTable": values,
            "LanguageTable": languoids.values(),
            "ParameterTable": segments,
            "inventories.csv": inventories,
        }
    )
    ds.validate(logging.getLogger(__name__))


if __name__ == "__main__":
    main(
        Path("~/.config/cldf/clts").expanduser(),
        Path("~/.config/cldf/glottolog").expanduser(),
    )
