import axios from 'axios';
import { getToken } from '../utils/session';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || (window.location.hostname === 'localhost' ? 'http://localhost:8000' : ''),
  timeout: 30000, // 30s timeout to handle LLM profile synthesis
});

// Attach the session token to every request. Student-scoped routes verify it and
// reject when the token identity doesn't match the requested student_id; without
// this header they would 401. Read per-request rather than captured at module load,
// so a token minted mid-session (login, OAuth) applies immediately.
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
