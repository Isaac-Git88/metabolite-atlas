# data/bmdb

Put **`bmdb_metabolites.xml`** here. It is the Bovine Metabolome Database download
(~450 MB, not in the repository): get it from <https://bmdb.ca/downloads> and unzip it
into this folder.

`pipeline/bmdb/extract_bmdb_concentrations.py` reads it from here, and everything
else in this folder is generated from it by `pipeline/bmdb/`.
