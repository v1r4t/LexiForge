import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import SampleBanner from './components/SampleBanner';
import Dashboard from './pages/Dashboard';
import CallDetail from './pages/CallDetail';
import ResultsPage from './pages/Results';

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-gray-50">
        <Header />
        <SampleBanner />
        <main>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/calls/:callId" element={<CallDetail />} />
            <Route path="/results" element={<ResultsPage />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
