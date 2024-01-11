##################################
Architecture of Nublado controller
##################################

The Nublado controller is a FastAPI application with three basic functions:

#. Prepull images to every Kubernetes node.
#. Manage user lab pods and their supporting environment.
#. Manage user file server pods and their supporting environment.

Internally, the code structure uses the handler-services-storage code structure documented in :sqr:`072`.
To try to keep the size of the major services, such as the user lab manager, manageable, there are several layers of services that coordinate.

This diagram attempts to provide a guide to the overall code structure.
The Kubernetes storage layer is further subdivided into per-resource storage layers, which are not shown in this graph to try to keep the graph more concise.

.. mermaid::
   :caption: Internal structure

   flowchart LR
     subgraph services
       prepuller(Prepuller)
       image(ImageService)
       lab(LabManager)
       fileserver(FileserverManager)
       image --> docker-source(DockerImageSource)
       image --> gar-source(GARImageSource)
       prepuller --> prepull-builder(PrepullerBuilder)
       prepuller --> image
       lab --> image
       lab --> lab-builder(LabBuilder)
       fileserver --> fileserver-builder(FileserverBuilder)
       lab-builder --> volume-builder(VolumeBuilder)
       fileserver-builder --> volume-builder
     end
     subgraph storage
       docker(DockerStorageClient)
       gar(GARStorageClient)
       metadata(MetadataStorage)
       fileserver-storage(FilserverStorage)
       fileserver-storage --> kubernetes(Kubernetes)
       lab-storage(LabStorage)
       lab-storage --> kubernetes
       node-storage(NodeStorage)
     end
     docker-source --> docker
     gar-source --> gar
     fileserver --> fileserver-storage
     lab --> metadata
     lab --> lab-storage
     prepuller --> metadata
     prepuller --> kubernetes
     image --> node-storage

     main(app) --> handlers
     handlers --> image
     handlers --> prepuller
     handlers --> lab
     handlers --> fileserver
     background(BackgroundTaskManager)
     background --> image
     background --> prepuller
     background --> lab
     background --> fileserver
