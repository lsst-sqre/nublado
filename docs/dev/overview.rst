###############
Design overview
###############

.. mermaid::
   :caption: Internal structure

   flowchart LR
     subgraph services
       prepuller(Prepuller)
       image(ImageService)
       events(EventManager)
       form(FormManager)
       sizes(SizeManager)
       lab(LabManager)
       image --> docker-source(DockerImageSource)
       image --> gar-source(GARImageSource)
       lab --> image
       lab --> events
       lab --> sizes
       lab --> usermap
       form --> sizes
       prepuller --> image
       events --> usermap
     end
     subgraph storage
       docker(DockerStorageClient)
       gar(GARStorageClient)
       kubernetes-nodes(K8sStorageClient.get_image_data)
       usermap(UserMap)
       kubernetes(K8sStorageClient)
       gafaelfawr(GafaelfawrStorageClient)
     end
     main(create_app) --> config(Config)
     main --> context(ProcessContext)
     config --> context
     main --> handlers
     context --> handlers
     context --> prepuller
     context --> image
     context --> events
     handlers --> gafaelfawr
     handlers --> lab
     handlers --> image
     handlers --> events
     handlers --> form
     handlers --> usermap
     docker-source --> docker
     gar-source --> gar
     prepuller --> kubernetes
     image --> kubernetes-nodes
     lab --> kubernetes
