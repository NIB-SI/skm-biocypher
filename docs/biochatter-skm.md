# Stress Knowledge Map use case

Stress Knowledge Map (SKM, [citation{Bleker2024}]) 
<!-- https://linkinghub.elsevier.com/retrieve/pii/S2590346224001901 -->
is a publicly available resource containing   current knowledge of biochemical, signalling, and regulatory molecular interactions in plants: notably, a highly curated model of plant stress signalling (PSS) containing 751 reactions, implemented as a knowledge graph. PSS was constructed by domain experts through curation of literature and database resources.

While an interactive explorer is available for PSS, the existing interface does not allow for complex queries, and much of the rich metadata is not directly available to users without needing to download and parse exports. Integrating a (RAG-enabled) LLM with PSS will enable researchers to query the knowledge graph using natural language, eliminating the need to parse data files, learn Cypher, or be deeply familiar with the schema details underlying the knowledge graph. 

The focus during the workshop was to develop an interface to PSS using BioCypher (PSS-BioCypher) and subsequently develop and test a BioChatter interface. 
    
## Outcomes

### Developing PSS-BioCypher

Three challenges had to be tackled in developing PSS-BioCyper:

1. PSS is a __real-time database__, in that an online contribution interface  interface allows users to add new information based on novel biological knowledge. On average 7 updates are made to PSS per week, while some weeks have seen over 100 updates. Users expect to be able to immediately access new or updated information in the database. For this reason, instead of creating PSS-BioCypher from flat file exports, the PSS adapter was developed to be directly fed from the Neo4j database. 
  
  In the future, the aim is to use this as a basis to incrementally build PSS-BioCypher, based on real-time updates to PSS. Feeding directly from the database will also allow updates to the schema and metadata, by only updating the adapter and not having to additionally update flat file exports. 

2. PSS takes into account cross species information and genetic redundancy by grouping genes that take part in the same functions into __functional clusters__. To incorporate this information into PSS-BioCypher, two approaches could be taken: 
    * Include functional clusters as nodes and as reaction participants. To enable queries on the gene information level (e.g. gene names and gene identifiers), additionally add gene nodes with `gene to functional cluster` edges. 
   * Explode each reaction edge on a functional cluster across all the genes assigned to the functional cluster. 
  
  To stay closely aligned to the existing PSS schema, the first option was used. 

3. PSS has a complex __schema__, based in reactions connection interacting entities (Fig. 1), instead of direct pairwise interactions. While pairwise interactions are more intuitive in a knowledge graph formalism, the richly curated detail of PSS as a model, its cross-species compatibility, and the need to be able to exchange the information in PSS with other domain standards (such as SBML, SBGN) means the schema of PSS is somewhat convoluted for users to interact with. 
 
  <center><img src="https://raw.githubusercontent.com/NIB-SI/skm-biocypher/refs/heads/main/docs/basic-reaction-labelled.png" alt="PSS schema of a catalysis reaction" width="350"><br>Figure 1: PSS schema of a catalysis reaction. </center><br> 
  
  While the ontology would allow PSS-BioCypher to maintain the reaction based formulation, for the intuition of both the user and ability for the LLM to interpret the structure, the schema of PSS was projected from reactions to pairwise interactions between the reaction participants. As an example, the reaction in Fig. 1 was projected as in Fig. 2.  
   
  <center><img src="https://raw.githubusercontent.com/NIB-SI/skm-biocypher/refs/heads/main/docs/reaction-to-biocypher.png" alt="PSS-BioCypher schema of a catalysis reaction" width="300"><br>Figure 2: PSS-BioCypher schema of a catalysis reaction.</center><br>
  
  Including the depicted catalysis, PSS has nine defined reaction types, each of which was projected to the new schema. The `schema_config.yaml` file (in the GitHub repository) contains information on how the projection was done. 

### Scientific questions

In preparation for the workshop, current users of SKM were surveyed for potential questions about PSS to set to the LLM. The following list of questions was compiled from the responses:

* Which proteins regulate MYC2?
* Which genes are regulated by MYC2?
* Does ABA regulate MYC2, or is it the other way around?
* In which pathways is gene X involved?
* Are genes X, Y, Z regulated by the same transcription factor(s)?
* Is NPR1 important in a plant’s response to a bacterial infection?
* What is the most plausible hypothesis for upregulation of genes X, Y, Z and downregulation of B, C, D observed in my RNA-seq experiment where I treated plant leaves with a phytohormone J?

These questions where used in testing the BioChatter interface. 

### SKM BioChatter

BioChatter was connected to PSS-BioCypher in two manners: by deploying a BioChatter-light instance and by connecting a jupyter notebook. The BioChatter light instance was successfully connected to PSS-BioCypher and could be used to ask simple questions. A notebook (available in the GitHub repository) was used to reproducibly test more questions and interact with the LLM via BioChatter functionalities `BioCypherPromptEngine` and `BioCypherQueryHandler`. 
 
BioChatter was able to provide correct Cypher to answer to a number of simple questions, for example:

> How many genes belong to the MYC2 functional cluster?
```
MATCH (:FunctionalCluster{name: 'MYC2'})-[:GeneBelongsToFunctionalCluster]->(g:Gene)
RETURN COUNT(g) as numberOfGenes;
```


> Which functional cluster does the gene with tair identifier AT1G64280 belong to?
```
MATCH (g:Gene {tair: 'AT1G64280'})-[:GeneToFunctionalCluster]->(fc:FunctionalCluster) RETURN fc.name
```

It was also successful with more complex questions: 

> Which nodes does MYC2 transcriptionally regulate?
```
MATCH (fc1:FunctionalCluster)-[:TranscriptionalActivation|:TranscriptionalInhibition]->(fc2:FunctionalCluster)
WHERE fc1.name = 'MYC2'
RETURN fc2
```

> Which nodes does AT1G32640 transcriptionally regulate?"
```
MATCH (g:Gene {tair: 'AT1G32640'})-[:GeneBelongsToFunctionalCluster]->(fc:FunctionalCluster)-[:TranscriptionalActivation|:TranscriptionalInhibition]->(targetFC:FunctionalCluster)<-[:GeneBelongsToFunctionalCluster]-(targetGene:Gene)
RETURN targetGene
```

In the above two cases, the LLM used the target designation ("MYC2" vs "AT1G32640") to correctly deduce the need to anchor the query on a functional cluster vs on a gene. However, in general it was not always successful. 

Another issue encountered was inferring the edge type of interest. When not explicitly including the type of interaction in the question, the LLM did not always correctly deduce the difference between physical interactions and functional cluster membership, the latter denoted by `gene belongs to functional cluster` edge (a BioLink `gene to gene family association`). The following question was intended to result in a list of functional clusters that have molecular interactions with MYC2, but instead the provided Cypher results in the functional clusters that the gene MYC2 belongs to:

> Which functional clusters does MYC2 interact with?
```
MATCH (:Gene {name: "MYC2"})-[:GeneBelongsToFunctionalCluster]->(fc:FunctionalCluster)
RETURN fc.name, fc.description, fc.url;
```

A more explicit question improved the result:

> Which other functional clusters does the MYC2 functional cluster have a molecular interaction with?
```
MATCH (:FunctionalCluster {name: "MYC2"})-[:ProteinProteinInteraction]->(otherCluster:FunctionalCluster)
RETURN otherCluster.name, otherCluster.description
```

The more complex scientific questions provided by the users will require improvements to the prompt and further development of the PSS-Biocypher scheme. However, the results here are very promising the LLM is able to, at this point, help users generate Cypher queries to interrogate PSS. 

## Future Work

Guided by the user provided questions and the current performance of the LLM, the BioCypher schema for PSS will undergo a number of iterations, improvements, and refinements. One immediate avenue for improvement is exploring the second option of the proposed two methods to deal with functional clusters, as the LLM occasionally struggled to extrapolate gene function via functions assigned to the functional clusters. Another issue we came across was inconsistent interpretation of gene name vs gene identifier (TAIR). This would also need improvements, perhaps by user instructions. 

Complementary to PSS, the Comprehensive Knowledge Network (CKN) contains over 26,234 entities and 488,390 pairwise interactions. CKN was constructed from a combination of database mining and manual curation, and was last updated in 2023. We are currently in the process of incorporating the BioCypher workflow into our planned update to CKN. In this endeavour, we hope to contribute a number of adapters to the BioCypher project (including the PSS-BioCypher adapter). This will also generate a much larger knowledge graph with the same schema as PSS-BioCypher, compatible with BioChatter. 

Finally, we plan to integrate a BioChatter RAG assistant in the SKM web page. The aim would be for the assistant to answer questions about the SKM knowledge graphs, provide information about the database schema, and help users formulate queries. 

It would be interesting to investigate, if such an assistant could also aid in curation of the database in the form of identifying missing information, providing literature reviews, and summarising new publications in the context of the knowledge currently in SKM. 

## GitHub repository
    
The following repository contains the full workflow and instructions to prepare PSS-BioCypher, and deploy a BioChatter-light instance that can provide cypher queries for PSS-BioCypher:
* https://github.com/NIB-SI/skm-biocypher
