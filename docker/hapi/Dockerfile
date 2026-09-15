FROM hapiproject/hapi:v8.10.0-3-tomcat@sha256:4699f6bc38c08d4726963f7f831ad3c8964486cdb740af6986e6b0a83d4432c4

USER 0

RUN mkdir -p /usr/local/tomcat/conf/Catalina/localhost \
    && chown -R 65532:0 \
        /usr/local/tomcat/conf \
        /usr/local/tomcat/webapps

COPY --chown=65532:0 docker/hapi/application.yaml \
    /usr/local/tomcat/conf/hapi-application.yaml

USER 65532

