# A-Eye Traffic Command Center - Execution Guide

Follow these steps to get the entire system up and running.

## 1. Prerequisites
Ensure you have the following installed:
- **Node.js** (v18 or higher recommended)
- **Docker Desktop** (running)
- **Git** (optional, for versioning)

---

## 2. Infrastructure (MinIO)
Start the MinIO object storage using Docker Compose. This provides the storage for incident videos.

```powershell
# Run this from the project root directory
docker-compose up -d
```
- **S3 API**: http://localhost:9000
- **Console**: http://localhost:9001 (Login: minioadmin / minioadmin123)

---

## 3. Backend Setup
Navigate to the backend directory and prepare the environment.

```powershell
# Go to backend folder
cd backend

# Install dependencies (only needed once)
npm install

# Initialize Prisma Client (only needed if schema changes)
npx prisma generate
```

---

## 4. Running the Backend
Start the server in development mode. It will automatically connect to MinIO and ensure the `aeye-uploads` bucket exists.

```powershell
# Run from the /backend directory
npm run dev
```
- **Server URL**: http://localhost:5000
- **Logs**: You should see "Server running on port 5000" and "MinIO bucket already exists."

---

## 5. Running the Frontend
The frontend consists of static HTML files in the project root. You can open them directly in your browser.

- **Login**: Open `index.html` in your browser.
- **Dashboard**: Once logged in, you will be redirected to `dashboard.html`.
- **Analytics**: Accessible via the "Analytics" link in the dashboard sidebar.

*Tip: For the best experience, you can use a simple static server like the VS Code "Live Server" extension.*

---

## 6. Testing the System (Simulation)
To simulate an AI camera detection (which uploads a video to MinIO), you can use the built-in mock script:

```powershell
# Run from the /backend directory
node seed.js
```
This will populate your database with initial incidents and test the system flow.
