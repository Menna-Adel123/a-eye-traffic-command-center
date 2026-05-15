require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const { ensureBucket } = require('./s3Client');

const authRoutes = require('./routes/auth');
const incidentRoutes = require('./routes/incidents');
const webhookRoutes = require('./routes/webhook');
const mockRoutes = require('./routes/mockThirdParties');

const app = express();

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Static uploads removed — videos are now served from MinIO



// Routes
app.use('/api/auth', authRoutes);
app.use('/api/incidents', incidentRoutes);
app.use('/api/webhooks', webhookRoutes);
app.use('/api/mocks', mockRoutes);

// Vercel health check and debugging
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', time: new Date().toISOString(), env: process.env.NODE_ENV });
});

// Catch-all for /api to help debug 404s
app.use('/api', (req, res) => {
  res.status(404).json({ error: `Route ${req.originalUrl} not found on backend (fallback)` });
});

const PORT = process.env.PORT || 5000;

// Ensure MinIO bucket exists (non-blocking)
ensureBucket().catch((err) => {
  console.error('Failed to initialize MinIO bucket:', err);
});

// Start server locally if not on Vercel
if (process.env.NODE_ENV !== 'production' && !process.env.VERCEL) {
  app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
  });
}

// Export for Vercel Serverless Functions
module.exports = app;
