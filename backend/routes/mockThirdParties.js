const express = require('express');
const router = express.Router();

// Mock Ambulance Dispatch
router.post('/ambulance/dispatch', (req, res) => {
  console.log('[MOCK THIRD PARTY] Ambulance dispatched for incident:', req.body);
  
  // Simulate network delay
  setTimeout(() => {
    res.json({
      success: true,
      jobId: `AMB-${Math.floor(Math.random() * 10000)}`,
      status: 'dispatched',
      message: 'Ambulance successfully dispatched to location.'
    });
  }, 500);
});

// Mock Police Traffic Unit Dispatch
router.post('/police/dispatch', (req, res) => {
  console.log('[MOCK THIRD PARTY] Police traffic unit dispatched for incident:', req.body);
  
  // Simulate network delay
  setTimeout(() => {
    res.json({
      success: true,
      jobId: `POL-${Math.floor(Math.random() * 10000)}`,
      status: 'dispatched',
      message: 'Traffic unit successfully dispatched to location.'
    });
  }, 500);
});

// Mock AI Model Retraining (False Alert)
router.post('/model/retrain', (req, res) => {
  console.log('[MOCK THIRD PARTY] Incident submitted to AI model for retraining:', req.body);
  
  // Simulate network delay
  setTimeout(() => {
    res.json({
      success: true,
      status: 'queued',
      message: 'Incident added to the retraining queue.'
    });
  }, 500);
});

module.exports = router;
