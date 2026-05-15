const express = require('express');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const authMiddleware = require('../middleware/auth');
const prisma = require('../prismaClient');
const nodemailer = require('nodemailer');
const crypto = require('crypto');

const router = express.Router();

const RESET_CODE_TTL_MS = 5 * 60 * 1000;

// POST /api/auth/login
router.post('/login', async (req, res) => {
  try {
    const { serviceId, password } = req.body;

    if (!serviceId || !password) {
      return res.status(400).json({ error: 'Service ID and password are required' });
    }

    const user = await prisma.user.findUnique({
      where: { serviceId },
    });

    if (!user) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const isMatch = await bcrypt.compare(password, user.passwordHash);
    if (!isMatch) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const payload = {
      id: user.id,
      serviceId: user.serviceId,
      name: user.name,
      role: user.role,
    };

    const token = jwt.sign(payload, process.env.JWT_SECRET, { expiresIn: '1d' });

    res.json({ token, user: payload });
  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// GET /api/auth/me
router.get('/me', authMiddleware, async (req, res) => {
  try {
    const user = await prisma.user.findUnique({
      where: { id: req.user.id },
      select: { id: true, serviceId: true, name: true, role: true, station: true },
    });

    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    res.json({ user });
  } catch (error) {
    console.error('Me error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// POST /api/auth/logout
router.post('/logout', authMiddleware, (req, res) => {
  res.json({ message: 'Logged out' });
});

// POST /api/auth/create-user (Admin Only)
router.post('/create-user', authMiddleware, async (req, res) => {
  try {
    if (req.user.role !== 'admin') {
      return res.status(403).json({ error: 'Forbidden: Admin access required' });
    }

    const { email, role, name, station } = req.body;

    if (!email || !role || !name) {
      return res.status(400).json({ error: 'Email, role, and name are required' });
    }

    // Check if user exists
    const existingUser = await prisma.user.findFirst({
      where: { email },
    });

    if (existingUser) {
      return res.status(400).json({ error: 'User with this email already exists' });
    }

    // Generate random password and service ID
    const generatedPassword = crypto.randomBytes(4).toString('hex');
    const serviceId = `OFF-${crypto.randomBytes(2).toString('hex').toUpperCase()}`;

    const salt = await bcrypt.genSalt(10);
    const passwordHash = await bcrypt.hash(generatedPassword, salt);

    const newUser = await prisma.user.create({
      data: {
        serviceId,
        email,
        passwordHash,
        name,
        role,
        station: station || null,
      },
    });

    // Send email using Nodemailer
    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: process.env.SMTP_EMAIL,
        pass: process.env.SMTP_PASSWORD,
      },
    });

    const mailOptions = {
      from: `"A-Eye Traffic Command" <${process.env.SMTP_EMAIL}>`,
      to: email,
      subject: 'Welcome to A-Eye Traffic Command Center - Your Credentials',
      html: `
        <h2>Welcome to A-Eye Traffic Command Center</h2>
        <p>Hello <strong>${name}</strong>,</p>
        <p>An administrator has created an account for you.</p>
        <p>Here are your login credentials:</p>
        <ul>
          <li><strong>Service ID:</strong> ${serviceId}</li>
          <li><strong>Password:</strong> ${generatedPassword}</li>
        </ul>
        <p>Please log in securely at your earliest convenience.</p>
      `,
    };

    await transporter.sendMail(mailOptions);

    res.status(201).json({ message: 'User created and email sent successfully', user: { id: newUser.id, serviceId, email, role } });
  } catch (error) {
    console.error('Create user error:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// POST /api/auth/request-password-reset
async function requestPasswordReset(req, res) {
  try {
    const { serviceId, email } = req.body;

    if (!serviceId && !email) {
      return res.status(400).json({ error: 'Service ID or email is required' });
    }

    const filters = [];
    if (serviceId) filters.push({ serviceId });
    if (email) filters.push({ email });

    const user = await prisma.user.findFirst({
      where: { OR: filters },
    });

    if (!user || !user.email) {
      return res.status(404).json({ error: 'User not found or no email associated with this account' });
    }

    const resetCode = Math.floor(100000 + Math.random() * 900000).toString();
    const resetCodeHash = await bcrypt.hash(resetCode, 10);
    const resetCodeExpiresAt = new Date(Date.now() + RESET_CODE_TTL_MS);

    await prisma.user.update({
      where: { id: user.id },
      data: { resetCodeHash, resetCodeExpiresAt },
    });

    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: process.env.SMTP_EMAIL,
        pass: process.env.SMTP_PASSWORD,
      },
    });

    const mailOptions = {
      from: `"A-Eye Support" <${process.env.SMTP_EMAIL}>`,
      to: user.email,
      subject: 'A-Eye Password Reset Code',
      html: `
        <h2>Password Reset Request</h2>
        <p>Hello <strong>${user.name}</strong>,</p>
        <p>Use the code below to reset your password. This code expires in 5 minutes.</p>
        <p style="font-size:20px;font-weight:700;letter-spacing:2px;">${resetCode}</p>
        <p>If you did not request this, please ignore this email.</p>
      `,
    };

    await transporter.sendMail(mailOptions);

    res.json({ message: 'Reset code sent to your email.' });
  } catch (error) {
    console.error('Request password reset error:', error);
    res.status(500).json({ error: 'Server error' });
  }
}

// POST /api/auth/forgot-password (alias)
router.post('/forgot-password', requestPasswordReset);

// POST /api/auth/verify-reset-code
async function verifyResetCode(req, res) {
  try {
    const { serviceId, email, code } = req.body;

    if (!code || (!serviceId && !email)) {
      return res.status(400).json({ error: 'Code and Service ID or email are required' });
    }

    const filters = [];
    if (serviceId) filters.push({ serviceId });
    if (email) filters.push({ email });

    const user = await prisma.user.findFirst({
      where: { OR: filters },
    });

    if (!user || !user.resetCodeHash || !user.resetCodeExpiresAt) {
      return res.status(400).json({ error: 'Invalid or expired reset code' });
    }

    if (user.resetCodeExpiresAt.getTime() < Date.now()) {
      await prisma.user.update({
        where: { id: user.id },
        data: { resetCodeHash: null, resetCodeExpiresAt: null },
      });
      return res.status(400).json({ error: 'Reset code expired' });
    }

    const isMatch = await bcrypt.compare(code, user.resetCodeHash);
    if (!isMatch) {
      return res.status(400).json({ error: 'Invalid reset code' });
    }

    res.json({ message: 'Code verified' });
  } catch (error) {
    console.error('Verify reset code error:', error);
    res.status(500).json({ error: 'Server error' });
  }
}

// POST /api/auth/reset-password
async function resetPassword(req, res) {
  try {
    const { serviceId, email, code, newPassword } = req.body;

    if (!newPassword || !code || (!serviceId && !email)) {
      return res.status(400).json({ error: 'Code, new password, and Service ID or email are required' });
    }

    if (newPassword.length < 8) {
      return res.status(400).json({ error: 'Password must be at least 8 characters' });
    }

    const filters = [];
    if (serviceId) filters.push({ serviceId });
    if (email) filters.push({ email });

    const user = await prisma.user.findFirst({
      where: { OR: filters },
    });

    if (!user || !user.resetCodeHash || !user.resetCodeExpiresAt) {
      return res.status(400).json({ error: 'Invalid or expired reset code' });
    }

    if (user.resetCodeExpiresAt.getTime() < Date.now()) {
      await prisma.user.update({
        where: { id: user.id },
        data: { resetCodeHash: null, resetCodeExpiresAt: null },
      });
      return res.status(400).json({ error: 'Reset code expired' });
    }

    const isMatch = await bcrypt.compare(code, user.resetCodeHash);
    if (!isMatch) {
      return res.status(400).json({ error: 'Invalid reset code' });
    }

    const passwordHash = await bcrypt.hash(newPassword, 10);

    await prisma.user.update({
      where: { id: user.id },
      data: {
        passwordHash,
        resetCodeHash: null,
        resetCodeExpiresAt: null,
      },
    });

    res.json({ message: 'Password reset successful' });
  } catch (error) {
    console.error('Reset password error:', error);
    res.status(500).json({ error: 'Server error' });
  }
}

router.post('/request-password-reset', requestPasswordReset);
router.post('/verify-reset-code', verifyResetCode);
router.post('/reset-password', resetPassword);

module.exports = router;
