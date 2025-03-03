# PSS-BioCypher and BioChatter

For development with a local PSS neo4j database, `skm-neo4j` is provided as a git submodule. 


```bash
git clone --recurse-submodules git@github.com:NIB-SI/skm-biocypher.git
```


Two environmental file need to be prepared:

1. PSS .env file
 ```bash
 mv skm-neo4j/.env.example skm-neo4j/.env
 ```
 This can be left as is with defaults. 


2. BioChatter app env file
 ```bash
 mv app.env.example app.env
 ```
To use BioChatter, this file needs to contain a valid `OPENAI_API_KEY`.

## 🛠 Usage

###

__To bring up PSS__

```bash
docker compose up pss
```

Go to http://localhost:7475/browser/

__To bring up PSS-BioCypher__

```bash
docker compose up deploy
```

Go to http://localhost:7474/browser/

__To bring up BioChatter__

```bash
docker compose up biochatter
```

Go to: http://localhost:8501/


__Notebooks__

To run the notebook locally, you can use poetry to install the dependencies:
```bash
poetry install
```

Deploy `jupyter lab` using:

```bash
poetry run jupyter lab
```

The notebook is in the folder `notebooks`. 

### Development notes

To prevent multiple edge in the PSS-BioCypher graph in the case of running  `build` and `import` multiple times, the following will clear out the edge and node tables:

```bash 
docker run -it -v skm-biocypher_biocypher_neo4j_volume:/data \
neo4j:4.4-enterprise sh -c "rm /data/build2neo/*.csv"
```

If PSS-BioCypher is already populated, `build` and `import` steps can be avoided by running 

```bash
docker compose up deploy --no-deps
```


### Structure
The project is structured as follows:
```
.
│  # Project setup
│
├── LICENSE
├── README.md
├── docs
├── pyproject.toml
│
│  # PSS submodule
│
├── skm_neo4j
│
│  # Docker setup
│
├── Dockerfile
├── docker
│   ├── biocypher_entrypoint_patch.sh
│   ├── create_table.sh
│   └── import.sh
├── docker-compose.yml
├── docker-variables.env
│
│  # Project pipeline
│
├── create_knowledge_graph.py
├── config
│   ├── biocypher_config.yaml
│   ├── biocypher_docker_config.yaml
│   └── schema_config.yaml
├── skm
│    └── adapters
│        └── pss_adapter.py
│
│
└── notebooks
```

The main components of the BioCypher pipeline are the
`create_knowledge_graph.py`, the configuration in the `config` directory, and
the adapter module in the `skm` directory. 

### Running the pipeline

`python create_knowledge_graph.py` will create a knowledge graph from the
example data included in this repository (borrowed from the [BioCypher
tutorial](https://biocypher.org/tutorial.html)). To do that, it uses the
following components:

- `create_knowledge_graph.py`: the main script that orchestrates the pipeline.
It brings together the BioCypher package with the data sources. To build a 
knowledge graph, you need at least one adapter (see below). For common 
resources, there may already be an adapter available in the BioCypher package or
in a separate repository. You can also write your own adapter, should none be
available for your data.

- `example_adapter.py` (in `template_package.adapters`): a module that defines
the adapter to the data source. In this case, it is a random generator script.
If you want to create your own adapters, we recommend to use the example adapter
as a blueprint and create one python file per data source, approproately named.
You can then import the adapter in `create_knowledge_graph.py` and add it to
the pipeline. This way, you ensure that others can easily install and use your 
adapters.

- `schema_config.yaml`: a configuration file (found in the `config` directory)
that defines the schema of the knowledge graph. It is used by BioCypher to map
the data source to the knowledge representation on the basis of ontology (see
[this part of the BioCypher 
tutorial](https://biocypher.org/tutorial-ontology.html)).

- `biocypher_config.yaml`: a configuration file (found in the `config` 
directory) that defines some BioCypher parameters, such as the mode, the 
separators used, and other options. More on its use can be found in the
[Documentation](https://biocypher.org/installation.html#configuration).

## 🐳 Docker

This repo also contains a `docker compose` workflow to create the example
database using BioCypher and load it into a dockerised Neo4j instance
automatically. To run it, simply execute `docker compose up -d` in the root 
directory of the project. This will start up a single (detached) docker
container with a Neo4j instance that contains the knowledge graph built by
BioCypher as the DB `neo4j` (the default DB), which you can connect to and
browse at localhost:7474. Authentication is deactivated by default and can be
modified in the `docker_variables.env` file (in which case you need to provide
the .env file to the deploy stage of the `docker-compose.yml`).

Regarding the BioCypher build procedure, the `biocypher_docker_config.yaml` file
is used instead of the `biocypher_config.yaml` (configured in
`scripts/build.sh`). Everything else is the same as in the local setup. The
first container (`build`) installs and runs the BioCypher pipeline, the second
container (`import`) installs Neo4j and runs the import, and the third container
(`deploy`) deploys the Neo4j instance on localhost. The files are shared using a
Docker Volume. This three-stage setup strictly is not necessary for the mounting
of a read-write instance of Neo4j, but is required if the purpose is to provide
a read-only instance (e.g. for a web app) that is updated regularly; for an
example, see the [meta graph
repository](https://github.com/biocypher/meta-graph). The read-only setting is
configured in the `docker-compose.yml` file
(`NEO4J_dbms_databases_default__to__read__only: "false"`) and is deactivated by
default.
