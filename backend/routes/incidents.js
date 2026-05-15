const express = require('express');
const authMiddleware = require('../middleware/auth');
const prisma = require('../prismaClient');

const router = express.Router();

const getBaseUrl = () => {
  if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
  return `http://localhost:${process.env.PORT || 5000}`;
};

// GET /api/incidents
router.get('/', authMiddleware, async (req, res) => {
  try {
    const { status, startDate, endDate } = req.query;
    let where = {};

    if (status) {
      where.status = { in: status.split(',') };
    }
    
    if (startDate || endDate) {
      where.detectedAt = {};
      if (startDate) where.detectedAt.gte = new Date(startDate);
      if (endDate) where.detectedAt.lte = new Date(endDate);
    }

    const incidents = await prisma.incident.findMany({
      where,
      orderBy: { detectedAt: 'desc' }
    });

    res.json({ incidents });
  } catch (error) {
    console.error('Fetch incidents error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// GET /api/incidents/:id
router.get('/:id', authMiddleware, async (req, res) => {
  try {
    const incident = await prisma.incident.findUnique({
      where: { incidentCode: req.params.id } // Frontend uses incidentCode like 'EMG-001' as id
    });

    if (!incident) {
      return res.status(404).json({ error: 'Incident not found' });
    }

    res.json({ incident });
  } catch (error) {
    console.error('Fetch incident error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// Helper for calculating response time in mins
const calcResponseMins = (detected, now) => {
  return parseFloat(((now - detected) / 1000 / 60).toFixed(1));
};

// PATCH /api/incidents/:id/dispatch
router.patch('/:id/dispatch', authMiddleware, async (req, res) => {
  try {
    const incidentCode = req.params.id;
    const { reviewNotes, severity } = req.body;
    const reviewedBy = req.user ? req.user.id : null;
    const now = new Date();
    
    const incident = await prisma.incident.findUnique({ where: { incidentCode } });
    if (!incident) return res.status(404).json({ error: 'Incident not found' });

    const updated = await prisma.incident.update({
      where: { incidentCode },
      data: {
        status: 'emergency',
        dispatchedAt: now,
        responseTimeMins: calcResponseMins(incident.detectedAt, now),
        reviewedBy,
        reviewedAt: now,
        reviewNotes,
        ...(severity && { severity })
      }
    });

    // Mock call to 3rd party ambulance system
    fetch(`${getBaseUrl()}/api/mocks/ambulance/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated)
    }).catch(e => console.error('Mock call failed:', e));

    res.json({ incident: updated });
  } catch (error) {
    console.error('Dispatch error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// PATCH /api/incidents/:id/traffic-unit
router.patch('/:id/traffic-unit', authMiddleware, async (req, res) => {
  try {
    const incidentCode = req.params.id;
    const { reviewNotes, severity } = req.body;
    const reviewedBy = req.user ? req.user.id : null;
    const now = new Date();
    
    const incident = await prisma.incident.findUnique({ where: { incidentCode } });
    if (!incident) return res.status(404).json({ error: 'Incident not found' });

    const updated = await prisma.incident.update({
      where: { incidentCode },
      data: {
        status: 'emergency', // Traffic unit also counts as emergency response
        dispatchedAt: now,
        responseTimeMins: calcResponseMins(incident.detectedAt, now),
        reviewedBy,
        reviewedAt: now,
        reviewNotes,
        ...(severity && { severity })
      }
    });

    // Mock call to 3rd party police system
    fetch(`${getBaseUrl()}/api/mocks/police/dispatch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated)
    }).catch(e => console.error('Mock call failed:', e));

    res.json({ incident: updated });
  } catch (error) {
    console.error('Traffic unit error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// PATCH /api/incidents/:id/false-alert
router.patch('/:id/false-alert', authMiddleware, async (req, res) => {
  try {
    const incidentCode = req.params.id;
    const { reviewNotes } = req.body;
    const reviewedBy = req.user ? req.user.id : null;
    const now = new Date();
    
    const updated = await prisma.incident.update({
      where: { incidentCode },
      data: {
        status: 'false-alert',
        resolvedAt: now,
        reviewedBy,
        reviewedAt: now,
        reviewNotes
      }
    });

    // Mock call to retrain model
    fetch(`${getBaseUrl()}/api/mocks/model/retrain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated)
    }).catch(e => console.error('Mock call failed:', e));

    res.json({ incident: updated });
  } catch (error) {
    console.error('False alert error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

module.exports = router;
