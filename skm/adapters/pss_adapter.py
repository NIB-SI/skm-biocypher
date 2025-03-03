import random
import string
import os
from enum import Enum, auto
from itertools import chain
from typing import Optional
from biocypher._logger import logger

from urllib.request import urlretrieve
from pathlib import Path
from itertools import combinations, product, permutations
from collections import defaultdict

import neo4j_utils as nu
import pandas as pd

logger.debug(f"Loading module {__name__}.")

CKN_NODE_URL = 'https://skm.nib.si/downloads/ckn-annot'


def get_link_entry(key, links, get_all=False):
    ''' Get first entry in list of "key:value" with key==key '''
    if get_all:
        values = []
        if links is None:
            return values
        for x in links:
            if x.startswith(f"{key}:"):
                values.append(x)
        return values
    else:
        value = None
        if links is None:
            return value
        for x in links:
            if x.startswith(f"{key}:"):
                value = x
                break
        return value


class ReactionParticipant:

    def __init__(self, name, _id, form, location):
        self.name = name
        self.id = _id
        self.form = form
        self.location = location


class PSSAdapter:
    """
    Adapter for the Plant Stress Signalling model (PSS) Neo4j database
    """

    def __init__(
        self,
        outputdir = None
    ):


        # read driver
        try:
            self.driver = nu.Driver(
                db_name="neo4j",
                db_user="neo4j",
                db_passwd="password",
                db_uri="bolt://pss:7687",
                multi_db=False,
                max_connection_lifetime=7200,
            )
        except Exception:
            print("Whooooops!")

        self.node_lookup = {}

        self.incidental_edges = []

        self.pathways = defaultdict(set)

        self.load_gene_annotations(outputdir)

    def load_gene_annotations(self, outputdir):
        """From CKN file """

        ckn_annotations_path = Path(outputdir) / "gene_annotations.tsv.gz"
        if not ckn_annotations_path.exists():
            print(f"\tDownloading gene annotations (CKN) to {ckn_annotations_path}", end=" ")
            urlretrieve(CKN_NODE_URL, ckn_annotations_path)
            print("Success.")

        node_df = pd.read_csv(ckn_annotations_path, na_values=[''], keep_default_na=False, sep="\t", compression="gzip")
        node_df = node_df[~node_df["TAIR"].isna()]
        node_df.set_index("node_ID", inplace=True, drop=False)

        node_df = node_df[["short_name", "synonyms", "full_name", "GMM", "node_type"]]
        node_df.columns = ["name", "synonyms", "description", "gomapman_annotations", "type"]

        node_df["taxon"] = "ncbitaxon:3702"
        node_df["species"] = "Arabidopsis thaliana"

        self.gene_annotations = node_df.to_dict('index')

    def get_nodes(self):
        """
        Returns a generator of node tuples for node types specified in the
        adapter constructor.
        """

        logger.info("Generating nodes.")

        # ----
        # Functional clusters
        # ----

        def get_functionalcluster_nodes_tx(tx):
            result = tx.run(
                "MATCH (n:FunctionalCluster)"
                "RETURN n AS node, labels(n) AS labels",
            )
            return result.data()

        with self.driver.session() as session:
            results = session.read_transaction(get_functionalcluster_nodes_tx)
            for res in results:
                try:
                    _id, _type, _props, _use = self.process_node(res)
                    if _use:
                        yield (_id, _type, _props)

                        for child_id, child_type, child_props in self.process_genes_of_functional_cluster(res["node"], _id):
                            yield (child_id, child_type, child_props)

                except Exception as e:
                    print("ERROR! (functionalcluster nodes)", e, res)


        # ----
        # Other nodes
        # ----

        def get_other_nodes_tx(tx):
            result = tx.run(
                "MATCH (n) "
                "WHERE NOT 'ReactionClass' in labels(n) AND NOT 'FunctionalClusterClass' in labels(n)"
                "RETURN n AS node, labels(n) AS labels",
            )
            return result.data()

        with self.driver.session() as session:
            results = session.read_transaction(get_other_nodes_tx)
            for res in results:
                try:
                    _id, _type, _props, _use = self.process_node(res)
                    if _use:
                        yield (_id, _type, _props)
                except Exception as e:
                    print("ERROR! (other nodes)", e, res)


        # ----
        # Reactions
        # ----


        # ----
        # Additional nodes (pathways, DOIs)
        # ----

        for _id, _type, _props in self.process_pathways():
            yield (_id, _type, _props)


    def get_edges(self):
        """
        Returns a generator of edge tuples for edge types specified in the
        adapter constructor.

        Args:

        """

        logger.info("Generating edges.")

        # ----
        # Incidental edges
        # ----

        for _id, source, target, _type, props in self.incidental_edges:
            yield _id, source, target, _type, props

        # ----
        # gene to foreign entity
        # ----

        def get_foreign_edges_tx(tx):
            result = tx.run(
                "MATCH (g:ForeignCoding)-[AGENT_OF]->(n:ForeignEntity)"
                "RETURN n.name AS target, g.name AS source",
            )
            return result.data()

        with self.driver.session() as session:
            results = session.read_transaction(get_foreign_edges_tx)
            for res in results:
                try:
                    source = self.node_lookup[res['source']]
                    target = self.node_lookup[res['target']]
                    yield None, source, target, "gene_of", {}
                except Exception as e:
                    print("ERROR! (foreign gene of)", e, res)


        # ----
        # Reactions
        # ----

        def get_reactions_tx(tx):
            '''
            Get all reactions with their substrates, products and modifiers
            '''
            result = tx.run(
                "MATCH p=(r:Reaction)-[]-()"
                "RETURN r AS reaction, collect(p) AS path"
            )
            return [r for r in result]

        with self.driver.session() as session:
            results = session.read_transaction(get_reactions_tx)
            for res in results:
                try:
                    for _id, source, target, _type, props in self.process_reaction(res):
                        yield _id, source, target, _type, props

                except Exception as e:
                    print("ERROR! (reaction)", e, res)

        # ----
        # Additional nodes (DOIs)
        # ----


    def get_node_count(self):
        """
        Returns the number of nodes generated by the adapter.
        """
        return len(list(self.get_nodes()))

    def process_reaction(self, res):
        '''
        Process reaction and return edges
        '''

        substrates = []
        products = []
        modifiers = []

        reaction = res["reaction"]
        reaction_identifier = reaction["reaction_id"]
        props = {
            "reaction_identifier": f"skm:{reaction_identifier}",
            "url": f"https://skm.nib.si/biomine/?reaction_id={reaction_identifier}"
        }
        if 'external_links' in reaction:
            refs = get_link_entry("doi", reaction["external_links"], get_all=True)
            if refs:
                props["references"] = refs

        for path in res["path"]:

            edge = path.relationships[0]
            edge_type = edge.type # edges only have 1 type

            if edge_type in ['SUBSTRATE', 'TRANSLOCATE_FROM']:

                # (1) source is SUBSTRATE
                key = 'source'
                name = edge.start_node['name']

                try:
                    _id = self.node_lookup[name]
                except KeyError:
                    print("ERROR!", "SUBSTRATE not in KG", name, f"{reaction_identifier}")
                    continue

                location = edge[f'{key}_location']
                form = edge[f'{key}_form']
                substrates.append(ReactionParticipant(name, _id, form, location))

            elif edge_type in ['PRODUCT', 'TRANSLOCATE_TO']:

                # (2) target is PRODUCT
                key = 'target'
                name = edge.end_node['name']

                try:
                    _id = self.node_lookup[name]
                except KeyError:
                    print("ERROR!", "SUBSTRATE not in KG", name, f"{reaction_identifier}")
                    continue

                location = edge[f'{key}_location']
                form = edge[f'{key}_form']
                products.append(ReactionParticipant(name, _id, form, location))

            elif edge_type in  ['INHIBITS',  'ACTIVATES']:

                # (1) source is MODIFIER
                key = 'source'
                name = edge.start_node['name']

                try:
                    _id = self.node_lookup[name]
                except KeyError:
                    print("ERROR!", "SUBSTRATE not in KG", name, f"{reaction_identifier}")
                    continue

                location = edge[f'{key}_location']
                form = edge[f'{key}_form']
                if form == "condition":
                    continue
                modifiers.append(ReactionParticipant(name, _id, form, location))

        match res["reaction"]["reaction_type"]:
            case "catalysis":
                return self.process_catalysis(reaction, substrates, products, modifiers, props.copy())

            case "translocation":
                return self.process_translocation(reaction, substrates, products, modifiers, props.copy())

            case "binding/oligomerisation":
                return self.process_binding(reaction, substrates, products, modifiers, props.copy())

            case "degradation/secretion":
                return self.process_degradation(reaction, substrates, products, modifiers, props.copy())

            case "transcriptional/translational repression":
                return self.process_transcriptional_inhibition(reaction, substrates, products, modifiers, props.copy())

            case "transcriptional/translational activation":
                return self.process_transcriptional_activation(reaction, substrates, products, modifiers, props.copy())

            case "protein activation":
                return self.process_protein_activation(reaction, substrates, products, modifiers, props.copy())

            case "protein deactivation":
                return self.process_protein_inhibition(reaction, substrates, products, modifiers, props.copy())

            case "dissociation":
                return self.process_dissociation(reaction, substrates, products, modifiers, props.copy())

            case "unknown":
                return []

            case "cleavage/auto-cleavage":
                return []

    def process_catalysis(self, reaction, substrates, products, modifiers, props):

        _id = None

        # TODO?
        # for (source, target) in permutations(substrates, 2):
        #     _type = ""
        #     yield _id, source.id, target.id, _type, props
        _type = "downstream_metabolite"
        for (source, target) in product(substrates, products):
            yield _id, source.id, target.id, _type, props

        _type = "enzyme_substrate"
        for (source, target) in product(modifiers, substrates):
            yield _id, source.id, target.id, _type, props

        _type = "enzyme_product"
        for (source, target) in product(modifiers, products):
            yield _id, source.id, target.id, _type, props

    def process_degradation(self, reaction, substrates, products, modifiers, props):

        _id = None

        _type = "enzyme_degradation"
        for (source, target) in product(modifiers, substrates):
            yield _id, source.id, target.id, _type, props

    def process_translocation(self, reaction, substrates, products, modifiers, props):

        _id = None

        _type = "transport_substrate"
        for (source, target) in product(modifiers, substrates):
            yield _id, source.id, target.id, _type, props

    def process_binding(self, reaction, substrates, products, modifiers, props):

        # modifiers TODO

        _id = None

        for (source, target) in permutations(substrates, 2):

            _type = "protein_protein_interaction"

            yield _id, source.id, target.id, _type, props

        for (source, target) in product(substrates, products):

            _type = "complex_subunits"

            yield _id, source.id, target.id, _type, props

        for (source, target) in product(modifiers, products):

            _type = "complex_formation_catalyst"

            yield _id, source.id, target.id, _type, props


    def process_protein_activation(self, reaction, substrates, products, modifiers, props):

        _id = None

        for (source, target) in product(modifiers, substrates):



            _type = "protein_activation"

            yield _id, source.id, target.id, _type, props

    def process_protein_inhibition(self, reaction, substrates, products, modifiers, props):

        _id = None

        for (source, target) in product(modifiers, substrates):

            _type = "protein_inhibition"

            yield _id, source.id, target.id, _type, props

    def process_transcriptional_activation(self, reaction, substrates, products, modifiers, props):

        _id = None

        # TODO
        # if "transcription" in reaction["reaction_mechanism"]:
        _props = props.copy()
        _props['causal_mechanism'] = "transcriptional regulation"
        for (source, target) in product(modifiers, substrates):

            _type = "transcriptional_activation"

            yield _id, source.id, target.id, _type, props

    def process_transcriptional_inhibition(self, reaction, substrates, products, modifiers, props):

        _id = None

        # TODO
        # if "transcription" in reaction["reaction_mechanism"]:
        props['causal_mechanism'] = "transcriptional regulation"
        _type = "transcriptional_inhibition"
        for (source, target) in product(modifiers, substrates):
            yield _id, source.id, target.id, _type, props

    def process_dissociation(self, reaction, substrates, products, modifiers, props):

        _id = None

        # TODO
        _type = "dissociation_product"
        for (source, target) in product(substrates, products):
            yield _id, source.id, target.id, _type, props

        _type = "dissociation_catalyst"
        for (source, target) in product(substrates, modifiers):
            yield _id, source.id, target.id, _type, props





    def process_node(self, res):

        for pathway in res["node"].get("all_pathways", []):
            self.pathways[pathway].add(res['node']['name'])

        if "Metabolite" in res["labels"]:
            return self.process_metabolite(res["node"])

        elif "Complex" in res["labels"]:
            return self.process_complex(res["node"])

        elif "ForeignEntity" in res["labels"]:
            return self.process_foreign_entity(res["node"])

        elif "ForeignAbiotic" in res["labels"]:
            return self.process_foreign_abiotic(res["node"])

        elif "ForeignCoding" in res["labels"]:
            return self.process_foreign_coding(res["node"])

        elif "Family" in res["labels"]:
            return self.process_family(res["node"])

        elif "Process" in res["labels"]:
            return self.process_process(res["node"])

        elif "FunctionalCluster" in res["labels"]:
            return self.process_functional_cluster(res)

        else:
            # print(res['labels'])
            return None, None, None, False

    def process_metabolite(self, data):

        _id = None

        if "external_links" in data:
            _id = get_link_entry("chebi", data['external_links'])

        _type = "metabolite"

        _props = {}
        _props["name"] = data["name"]
        _props["description"] = data.get("description", "")


        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_complex(self, data):

        _id = None
        _type = "complex"

        _props = {}
        _props["name"] = data["name"]
        _props["description"] = data.get("description", "")

        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_foreign_entity(self, data):

        _id = None
        if "external_links" in data:
            _id = get_link_entry("ncbitaxon", data['external_links'])

        _type = data["classification"]

        _props = {}
        _props["name"] = data["name"]
        _props["description"] = data.get("description", "")

        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_foreign_abiotic(self, data):

        _id = None
        _type = "environmental_process"

        _props = {}
        _props["name"] = data["name"]
        _props["description"] = data.get("description", "")


        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_foreign_coding(self, data):

        _id = None
        _type = "foreign_gene"

        _props = {}
        _props["name"] = data["name"]
        _props["description"] = data.get("description", "")

        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_family(self, data):

        _id = None
        _type = "gene_family"

        _props = {}
        _props["name"] = data["name"]
        _props["description"] = data.get("description", "")

        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_process(self, data):

        _id = None
        _type = "biological_process"

        _props = {}
        _props["name"] = data["name"]
        _props["description"] = data.get("description", "")

        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_functional_cluster(self, res):

        data = res["node"]

        fc = data["functional_cluster_id"]
        _id = f"skm:{fc}"
        _type = "functional_cluster"

        _props = {}
        _props["name"] = data["short_name"]
        _props["description"] = data.get("description", "")

        a = data.get("additional_information", "")
        _props["additional_information"] = a.replace('"', '').replace("'", "")

        _props["url"] = f"https://skm.nib.si/biomine/?functional_cluster_id={fc}"

        if _id is None:
            _id = f"pss:{data['name']}"
        self.node_lookup[data['name']] = _id

        return _id, _type, _props, True

    def process_genes_of_functional_cluster(self, data, target):

        for ath in data.get("ath_homologues", []):
            _id = f"tair:{ath}"
            _type = "gene"
            _props = self.gene_annotations[ath]
            _props["url"] = f"https://skm.nib.si/search?entity_type=functional_cluster&key=identifier&query={ath}"
            _props["tair"] = ath

            self.incidental_edges.append((None, _id, target, "functional_cluster_member", {}))

            yield _id, _type, _props

    def process_pathways(self):

        for p in self.pathways:
            _props = {"name": p}
            _id = f"pss:{p}"

            for n in self.pathways[p]:
                print(p, n, _id, "pathway")
                self.incidental_edges.append((None, n, _id, "in_pathway", {}))

            yield (_id, "pathway", _props)


# class Node:
#     self.id = None
#     self.label = None
#     self.properties = {}

#     def get_id(self):
#         """
#         Returns the node id.
#         """
#         return self.id

#     def get_label(self):
#         """
#         Returns the node label.
#         """
#         return self.label

#     def get_properties(self):
#         """
#         Returns the node properties.
#         """
#         return self.properties