# MinIO development container

The upstream MinIO project was archived in 2026 and its official registry images
were withdrawn. This image builds the final security-fixed community source tag,
`RELEASE.2025-10-15T17-29-55Z`, at pinned commit
`9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`.

The container is intended for this local/hackathon Compose stack. For a hosted
deployment, review MinIO's archived status and consider a maintained
S3-compatible service. The Workbench application uses only the S3-compatible
API through the Python MinIO client.
