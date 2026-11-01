import { Activity } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function Header() {
  return (
    <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <Link to="/" className="flex items-center space-x-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-cyan-500 rounded-lg flex items-center justify-center">
              <Activity className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">LexiForge</h1>
              <p className="text-xs text-gray-500">Vocabulary-Risk Testing Framework</p>
            </div>
          </Link>
          <nav className="flex items-center space-x-6">
            <Link to="/" className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors">
              Dashboard
            </Link>
            <Link to="/results" className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors">
              Results
            </Link>
            <a href="https://www.gnani.ai/" target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-gray-700 hover:text-blue-600 transition-colors">
              Gnani AI
            </a>
          </nav>
        </div>
      </div>
    </header>
  );
}
