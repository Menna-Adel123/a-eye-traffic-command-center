let resetIdentifier = {};
let resetCode = '';
let countdownTimer = null;
let countdownRemainingMs = 5 * 60 * 1000;

const requestStep = document.getElementById('requestStep');
const verifyStep = document.getElementById('verifyStep');
const resetStep = document.getElementById('resetStep');
const countdownEl = document.getElementById('codeCountdown');
const snackbar = document.getElementById('snackbar');

function showStep(step) {
  requestStep.classList.add('hidden');
  verifyStep.classList.add('hidden');
  resetStep.classList.add('hidden');

  if (step === 'request') requestStep.classList.remove('hidden');
  if (step === 'verify') verifyStep.classList.remove('hidden');
  if (step === 'reset') resetStep.classList.remove('hidden');
}

function showSnackbar(message, type) {
  snackbar.textContent = message;
  snackbar.className = `snackbar ${type || ''}`.trim();
  requestAnimationFrame(() => snackbar.classList.add('show'));
  setTimeout(() => snackbar.classList.remove('show'), 3000);
}

function startCountdown() {
  clearInterval(countdownTimer);
  countdownRemainingMs = 5 * 60 * 1000;
  updateCountdown();
  countdownTimer = setInterval(() => {
    countdownRemainingMs -= 1000;
    updateCountdown();
    if (countdownRemainingMs <= 0) {
      clearInterval(countdownTimer);
      showSnackbar('Reset code expired. Please request a new one.', 'error');
      showStep('request');
    }
  }, 1000);
}

function updateCountdown() {
  const totalSeconds = Math.max(0, Math.floor(countdownRemainingMs / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
  const seconds = String(totalSeconds % 60).padStart(2, '0');
  countdownEl.textContent = `${minutes}:${seconds}`;
}

function buildIdentifier() {
  const serviceId = document.getElementById('serviceId').value.trim();
  const email = document.getElementById('email').value.trim();
  if (!serviceId && !email) {
    showSnackbar('Enter a Service ID or email.', 'error');
    return null;
  }
  return { serviceId: serviceId || undefined, email: email || undefined };
}

requestStep.addEventListener('submit', async (event) => {
  event.preventDefault();
  const identifier = buildIdentifier();
  if (!identifier) return;

  const submitBtn = requestStep.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Sending...';

  try {
    const response = await fetch('/api/auth/request-password-reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(identifier)
    });

    const data = await response.json();
    if (response.ok) {
      resetIdentifier = identifier;
      showSnackbar(data.message || 'Reset code sent.', 'success');
      showStep('verify');
      startCountdown();
    } else {
      showSnackbar(data.error || 'Failed to send reset code.', 'error');
    }
  } catch (error) {
    console.error('Request reset error:', error);
    showSnackbar('Server connection error.', 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Send Reset Code';
  }
});

verifyStep.addEventListener('submit', async (event) => {
  event.preventDefault();
  const codeInput = document.getElementById('resetCode');
  const code = codeInput.value.trim();
  if (!code) {
    showSnackbar('Enter the reset code.', 'error');
    return;
  }

  const submitBtn = verifyStep.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Verifying...';

  try {
    const response = await fetch('/api/auth/verify-reset-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...resetIdentifier, code })
    });

    const data = await response.json();
    if (response.ok) {
      resetCode = code;
      showSnackbar(data.message || 'Code verified.', 'success');
      showStep('reset');
    } else {
      showSnackbar(data.error || 'Invalid code.', 'error');
    }
  } catch (error) {
    console.error('Verify code error:', error);
    showSnackbar('Server connection error.', 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Verify Code';
  }
});

resetStep.addEventListener('submit', async (event) => {
  event.preventDefault();
  const newPassword = document.getElementById('newPassword').value.trim();
  const confirmPassword = document.getElementById('confirmPassword').value.trim();

  if (!newPassword || !confirmPassword) {
    showSnackbar('Enter and confirm your new password.', 'error');
    return;
  }

  if (newPassword !== confirmPassword) {
    showSnackbar('Passwords do not match.', 'error');
    return;
  }

  const submitBtn = resetStep.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Updating...';

  try {
    const response = await fetch('/api/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...resetIdentifier, code: resetCode, newPassword })
    });

    const data = await response.json();
    if (response.ok) {
      showSnackbar(data.message || 'Password updated.', 'success');
      setTimeout(() => {
        window.location.href = 'index.html';
      }, 1500);
    } else {
      showSnackbar(data.error || 'Password reset failed.', 'error');
    }
  } catch (error) {
    console.error('Reset password error:', error);
    showSnackbar('Server connection error.', 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Update Password';
  }
});

