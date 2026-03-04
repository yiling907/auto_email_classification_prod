import React from 'react'
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import EmailsList from './pages/EmailsList'
import EmailDetail from './pages/EmailDetail'
import ModelMetrics from './pages/ModelMetrics'
import RAGMetrics from './pages/RAGMetrics'
import './App.css'

// Set API base URL from environment or default
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:3001'

function App() {
  return (
    <Router>
      <div className="app">
        <nav className="navbar">
          <div className="nav-container">
            <h1 className="nav-title">InsureMail AI Dashboard</h1>
            <div className="nav-links">
              <Link to="/">Overview</Link>
              <Link to="/emails">Emails</Link>
              <Link to="/models">Model Performance</Link>
              <Link to="/rag">RAG Effectiveness</Link>
            </div>
          </div>
        </nav>

        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard apiUrl={API_BASE_URL} />} />
            <Route path="/emails" element={<EmailsList apiUrl={API_BASE_URL} />} />
            <Route path="/email/:emailId" element={<EmailDetail apiUrl={API_BASE_URL} />} />
            <Route path="/models" element={<ModelMetrics apiUrl={API_BASE_URL} />} />
            <Route path="/rag" element={<RAGMetrics apiUrl={API_BASE_URL} />} />
          </Routes>
        </main>

        <footer className="footer">
          <p>InsureMail AI - Powered by Claude 3 on AWS Bedrock</p>
        </footer>
      </div>
    </Router>
  )
}

export default App
