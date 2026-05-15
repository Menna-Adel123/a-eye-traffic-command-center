# Frontend Deployment Guide

This guide explains how to deploy new frontend code changes to your live site on Vercel. 

Your Vercel project is fully linked to your GitHub repository. This means deployments are **100% automated**.

### How to Deploy Code Changes

Whenever you make changes to your code and want to push them to the live website, simply use your normal Git workflow:

```bash
# 1. Add your new code changes
git add .

# 2. Commit your changes
git commit -m "Update dashboard colors and fix button bug"

# 3. Push to GitHub
git push origin main
```

*That's it!* 

Vercel constantly watches your `main` branch. Within seconds of running the `git push origin main` command, Vercel will automatically detect the changes, build the site, and seamlessly update your live URL (`https://a-eye-traffic-command-center.vercel.app`).

You do not need to run any special deployment commands. The `git push` does everything for you!
