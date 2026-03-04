#!/bin/bash
# Create the default S3 bucket for development
awslocal s3 mb s3://echoroo
echo "Bucket 'echoroo' created successfully"

# Configure CORS on the bucket for browser-based uploads via presigned URLs
awslocal s3api put-bucket-cors --bucket echoroo --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["http://localhost:5173", "http://localhost:3000"],
      "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag", "x-amz-version-id"],
      "MaxAgeSeconds": 3600
    }
  ]
}'
echo "CORS configuration applied to bucket 'echoroo'"
