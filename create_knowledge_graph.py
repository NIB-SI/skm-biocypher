from biocypher import BioCypher, Resource
from skm.adapters.pss_adapter import (
    PSSAdapter,
)

# Instantiate the BioCypher interface
# You can use `config/biocypher_config.yaml` to configure the framework or
# supply settings via parameters below
bc = BioCypher()

bc.show_ontology_structure(to_disk="./")

# Create a protein adapter instance
adapter = PSSAdapter(
    outputdir = "./data"
)


# Create a knowledge graph from the adapter
bc.write_nodes(adapter.get_nodes())
bc.write_edges(adapter.get_edges())

# Write admin import statement
bc.write_import_call()

bc.write_schema_info(as_node=True)
# Print summary
# bc.summary()
