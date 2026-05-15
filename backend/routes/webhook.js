const express = require('express');
const multer = require('multer');
const multerS3 = require('multer-s3');
const prisma = require('../prismaClient');
const { s3Client, BUCKET_NAME } = require('../s3Client');

const router = express.Router();

// Configure multer — fall back to memory storage if S3 is unavailable
let upload;
try {
  upload = multer({
    storage: multerS3({
      s3: s3Client,
      bucket: BUCKET_NAME,
      contentType: multerS3.AUTO_CONTENT_TYPE,
      key: function (req, file, cb) {
        const uniqueName = Date.now() + '-' + file.originalname;
        cb(null, `videos/${uniqueName}`);
      }
    })
  });
} catch (err) {
  console.warn('S3 not available, falling back to memory storage:', err.message);
  upload = multer({ storage: multer.memoryStorage() });
}

// POST /api/webhooks/ai-detection
router.post('/ai-detection', (req, res, next) => {
  upload.single('video')(req, res, (err) => {
    if (err) {
      console.warn('File upload failed, continuing without video:', err.message);
      req.file = null;
    }
    next();
  });
}, async (req, res) => {
  try {
    const { incidentCode, type, severity, confidence, locationName, latitude, longitude, camera } = req.body;
    
    // Validate required fields
    if (!incidentCode || !type || !latitude || !longitude) {
      return res.status(400).json({ error: 'Missing required fields' });
    }

    // Build the public URL for the uploaded video
    const videoUrl = req.file
      ? (process.env.S3_PUBLIC_URL 
          ? `${process.env.S3_PUBLIC_URL}/${req.file.key}` 
          : `http://${process.env.MINIO_ENDPOINT || 'localhost'}:${process.env.MINIO_PORT || 9000}/${BUCKET_NAME}/${req.file.key}`)
      : null;

    const newIncident = await prisma.incident.create({
      data: {
        incidentCode,
        type,
        severity: severity || 'low',
        confidence: parseFloat(confidence) || 0,
        locationName: locationName || 'Unknown',
        latitude: parseFloat(latitude),
        longitude: parseFloat(longitude),
        camera: camera || 'Unknown',
        videoUrl,
        status: 'pending'
      }
    });


    res.status(201).json({ success: true, incident: newIncident });
  } catch (error) {
    console.error('Webhook error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

module.exports = router;
