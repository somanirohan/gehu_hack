import React from 'react'
import { createRoot } from 'react-dom/client'
import 'leaflet/dist/leaflet.css'
import './styles.css'
import App from './App.jsx'

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register('/responder/sw.js', { scope: '/responder/' }).catch(() => {})
}
createRoot(document.getElementById('root')).render(<App />)
