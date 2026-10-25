# oasees/ml-base-image plus safetensors, which the FL server and the model loaders now need.
# Use it by setting OASEES_ML_IMAGE (see README), or ask the owner of oasees/ml-base-image to add the package.
#
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     -t <registry>/ml-base-image:safetensors --push docker/ml-base-image
#
# The base image unpacks to several GB per architecture (TensorFlow and torch). Where that
# is too much for the build machine, appending these same files as a layer with
# `crane append` gives the same result.
FROM oasees/ml-base-image:latest
USER root
RUN pip install --no-cache-dir safetensors==0.8.0
USER oasees
