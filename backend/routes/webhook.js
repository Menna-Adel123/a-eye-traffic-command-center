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

const normalizeSeverity = (value) => {
  const severity = String(value || 'low').toLowerCase();
  if (['low', 'medium', 'high'].includes(severity)) return severity;
  return 'low';
};

const parseNumber = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const buildIncidentCode = () => {
  const timestamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `AI-${timestamp}-${suffix}`;
};

const verifySharedSecret = (req, res) => {
  const expectedSecret = process.env.AI_WEBHOOK_SECRET;
  if (!expectedSecret) return true;

  const receivedSecret = req.get('x-ai-webhook-secret');
  if (receivedSecret !== expectedSecret) {
    res.status(401).json({
      success: false,
      error: 'Invalid or missing AI webhook secret'
    });
    return false;
  }

  return true;
};

const uploadVideoIfMultipart = (req, res, next) => {
  if (!req.is('multipart/form-data')) return next();

  upload.single('video')(req, res, (err) => {
    if (err) {
      console.warn('File upload failed, continuing without video:', err.message);
      req.file = null;
    }
    next();
  });
};

const getUploadedVideoUrl = (req) => {
  if (!req.file) return null;

  if (process.env.S3_PUBLIC_URL) {
    return `${process.env.S3_PUBLIC_URL}/${req.file.key}`;
  }

  return `http://${process.env.MINIO_ENDPOINT || 'localhost'}:${process.env.MINIO_PORT || 9000}/${BUCKET_NAME}/${req.file.key}`;
};

// POST /api/webhooks/ai-detection
router.post('/ai-detection', uploadVideoIfMultipart, async (req, res) => {
  try {
    if (!verifySharedSecret(req, res)) return;

    const body = req.body || {};
    const metadata = typeof body.metadata === 'string'
      ? JSON.parse(body.metadata || '{}')
      : (body.metadata || {});

    const latitude = parseNumber(body.latitude);
    const longitude = parseNumber(body.longitude);
    const confidence = parseNumber(body.confidence);

    const errors = [];
    if (!body.type) errors.push('type is required');
    if (latitude === null) errors.push('latitude must be a valid number');
    if (longitude === null) errors.push('longitude must be a valid number');
    if (confidence === null) errors.push('confidence must be a valid number');

    if (errors.length > 0) {
      return res.status(400).json({
        success: false,
        error: 'Validation failed',
        details: errors
      });
    }

    const uploadedVideoUrl = getUploadedVideoUrl(req);
    const incomingMediaUrl = body.videoUrl || body.snapshotUrl || body.snapshotPath || metadata.snapshot_path || null;
    const detectedAt = body.detectedAt ? new Date(body.detectedAt) : new Date();

    const newIncident = await prisma.incident.create({
      data: {
        incidentCode: body.incidentCode || buildIncidentCode(),
        type: body.type,
        severity: normalizeSeverity(body.severity),
        confidence,
        locationName: body.locationName || 'Unknown',
        latitude,
        longitude,
        camera: body.camera || 'Unknown',
        videoUrl: uploadedVideoUrl || incomingMediaUrl,
        status: 'pending',
        detectedAt: Number.isNaN(detectedAt.getTime()) ? new Date() : detectedAt
      }
    });

    res.status(201).json({
      success: true,
      message: 'AI detection received and incident created',
      incident: newIncident
    });
  } catch (error) {
    if (error && error.code === 'P2002') {
      return res.status(409).json({
        success: false,
        error: 'Duplicate incidentCode'
      });
    }

    console.error('Webhook error:', error);
    res.status(500).json({
      success: false,
      error: 'Server error'
    });
  }
});

module.exports = router;
