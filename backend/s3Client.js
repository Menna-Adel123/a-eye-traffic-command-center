const { S3Client, CreateBucketCommand, HeadBucketCommand, PutBucketPolicyCommand } = require('@aws-sdk/client-s3');

const endpointUrl = process.env.S3_ENDPOINT || `http://${process.env.MINIO_ENDPOINT || 'localhost'}:${process.env.MINIO_PORT || 9000}`;

const s3Client = new S3Client({
  endpoint: endpointUrl,
  region: process.env.S3_REGION || 'us-east-1',
  credentials: {
    accessKeyId: process.env.MINIO_ACCESS_KEY || 'minioadmin',
    secretAccessKey: process.env.MINIO_SECRET_KEY || 'minioadmin123',
  },
  forcePathStyle: true, // Required for MinIO and Supabase S3
});

const BUCKET_NAME = process.env.MINIO_BUCKET || 'aeye-uploads';

/**
 * Ensures the MinIO bucket exists and has a public-read policy for serving files.
 */
async function ensureBucket() {
  try {
    await s3Client.send(new HeadBucketCommand({ Bucket: BUCKET_NAME }));
    console.log(`MinIO bucket "${BUCKET_NAME}" already exists.`);
  } catch (err) {
    if (err.name === 'NotFound' || err.$metadata?.httpStatusCode === 404) {
      console.log(`Creating MinIO bucket "${BUCKET_NAME}"...`);
      await s3Client.send(new CreateBucketCommand({ Bucket: BUCKET_NAME }));

      // Set public read policy so videos can be accessed directly
      const policy = {
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'PublicRead',
            Effect: 'Allow',
            Principal: '*',
            Action: ['s3:GetObject'],
            Resource: [`arn:aws:s3:::${BUCKET_NAME}/*`],
          },
        ],
      };

      await s3Client.send(
        new PutBucketPolicyCommand({
          Bucket: BUCKET_NAME,
          Policy: JSON.stringify(policy),
        })
      );

      console.log(`MinIO bucket "${BUCKET_NAME}" created with public-read policy.`);
    } else {
      console.error('Error checking MinIO bucket:', err);
      throw err;
    }
  }
}

module.exports = { s3Client, BUCKET_NAME, ensureBucket };
