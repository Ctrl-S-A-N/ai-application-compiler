import { useState } from 'react';

const API_BASE =
  import.meta.env.VITE_API_URL || "http://localhost:8000";

type CompileResponse = {
  intent_ir: any;
  architecture: any;
  ui_schema: any;
  api_schema: any;
  db_schema: any;
  auth_schema: any;
  validation_report: any;
  repair_report: any;
  runtime_report: any;
};

export default function App() {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<CompileResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<keyof CompileResponse | 'summary'>('summary');

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    setData(null);
    
    try {
      const response = await fetch(`${API_BASE}/api/compile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt })
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const result: CompileResponse = await response.json();
      setData(result);
      setActiveTab('summary');
    } catch (err: any) {
      setError(err.message || 'An error occurred during compilation.');
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const tabs: { key: keyof CompileResponse | 'summary'; label: string }[] = [
    { key: 'summary', label: 'Summary' },
    { key: 'intent_ir', label: 'Intent IR' },
    { key: 'architecture', label: 'Architecture Manifest' },
    { key: 'ui_schema', label: 'UI Schema' },
    { key: 'api_schema', label: 'API Schema' },
    { key: 'db_schema', label: 'Database Schema' },
    { key: 'auth_schema', label: 'Auth Schema' },
    { key: 'validation_report', label: 'Validation Report' },
    { key: 'repair_report', label: 'Repair Report' },
    { key: 'runtime_report', label: 'Runtime Generation Report' }
  ];

  const renderSummary = () => {
    if (!data) return null;
    return (
      <div className="p-4 bg-white rounded border border-gray-200">
        <h3 className="font-bold text-lg mb-4 border-b pb-2">Application Summary</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div><span className="font-semibold text-gray-600">Application Type:</span> {data.intent_ir?.application_type || 'N/A'}</div>
          <div><span className="font-semibold text-gray-600">Features:</span> {data.intent_ir?.features?.map((f: any) => f.name).join(', ') || 'None'}</div>
          <div><span className="font-semibold text-gray-600">Roles:</span> {data.intent_ir?.roles?.map((r: any) => r.name).join(', ') || 'None'}</div>
          <div><span className="font-semibold text-gray-600">Pages:</span> {data.architecture?.pages?.map((p: any) => p.name).join(', ') || 'None'}</div>
          <div><span className="font-semibold text-gray-600">Database Tables:</span> {data.db_schema?.tables?.map((t: any) => t.name).join(', ') || 'None'}</div>
          <div><span className="font-semibold text-gray-600">API Endpoint Count:</span> {data.api_schema?.endpoints?.length || 0}</div>
          <div><span className="font-semibold text-gray-600">Validation Status:</span> {data.validation_report?.valid ? <span className="text-green-600">Valid</span> : <span className="text-red-600">Invalid</span>}</div>
          <div>
            <span className="font-semibold text-gray-600">Repair Status:</span> {
              data.repair_report 
                ? (data.repair_report.revalidation_passed ? <span className="text-green-600">Repaired Successfully</span> : <span className="text-red-600">Repair Failed</span>)
                : <span className="text-gray-500">Not Required</span>
            }
          </div>
          <div><span className="font-semibold text-gray-600">Runtime Status:</span> {data.runtime_report?.success ? <span className="text-green-600">Success</span> : <span className="text-red-600">Failed</span>}</div>
        </div>
      </div>
    );
  };

  const renderJsonViewer = (content: any) => {
    if (activeTab === 'summary') return renderSummary();
    if (!content) return <div className="p-4 text-gray-500">No data available (Skipped or Empty)</div>;
    const jsonString = JSON.stringify(content, null, 2);
    return (
      <div className="relative group">
        <button 
          onClick={() => handleCopy(jsonString)}
          className="absolute top-2 right-2 bg-blue-600 text-white px-2 py-1 rounded text-xs opacity-0 group-hover:opacity-100 transition-opacity"
        >
          Copy
        </button>
        <pre className="p-4 bg-gray-900 text-gray-100 rounded overflow-auto text-sm max-h-[800px]">
          {jsonString}
        </pre>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gray-100 p-6 flex flex-col md:flex-row gap-6">
      <div className="w-full md:w-1/3 flex flex-col gap-4 bg-white p-4 shadow rounded-lg h-fit border border-gray-200">
        <h1 className="text-2xl font-bold text-gray-800">Pipeline Demo</h1>
        <p className="text-gray-500 text-sm mb-2">Test and visualize compiler outputs.</p>
        
        <div className="flex flex-col gap-2">
          <label className="font-semibold text-gray-700">Enter Prompt:</label>
          <textarea 
            className="w-full h-48 p-3 border border-gray-300 rounded resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            placeholder="e.g. Build a CRM with contacts and users..."
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
          />
          <button 
            className={`mt-2 p-2 rounded text-white font-bold transition-colors ${loading || !prompt.trim() ? 'bg-blue-300 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'}`}
            onClick={handleGenerate}
            disabled={loading || !prompt.trim()}
          >
            {loading ? 'Compiling...' : 'Generate Pipeline'}
          </button>
        </div>

        {error && (
          <div className="p-3 bg-red-100 text-red-700 rounded border border-red-200 text-sm">
            {error}
          </div>
        )}

        {loading && (
          <div className="mt-4 p-4 border border-blue-100 rounded bg-blue-50">
            <h3 className="font-bold mb-2 text-blue-800">Progress</h3>
            <ul className="text-sm space-y-2 text-blue-600">
              <li className="flex items-center gap-2"><span className="animate-spin">⏳</span> Intent Extraction</li>
              <li className="flex items-center gap-2">⏳ Architecture Planning</li>
              <li className="flex items-center gap-2">⏳ Schema Generation</li>
              <li className="flex items-center gap-2">⏳ Validation</li>
              <li className="flex items-center gap-2">⏳ Repair</li>
              <li className="flex items-center gap-2">⏳ Runtime Generation</li>
            </ul>
          </div>
        )}

        {data && !loading && (
          <div className="mt-4 p-4 border border-green-100 rounded bg-green-50">
            <h3 className="font-bold text-green-800 mb-2">Pipeline Completed</h3>
            <ul className="text-sm space-y-2 text-green-700">
              <li className="flex items-center gap-2">✓ Intent Extraction</li>
              <li className="flex items-center gap-2">✓ Architecture Planning</li>
              <li className="flex items-center gap-2">✓ Schema Generation</li>
              <li className="flex items-center gap-2">✓ Validation</li>
              <li className="flex items-center gap-2">✓ Repair {data.repair_report ? '(Executed)' : '(Skipped)'}</li>
              <li className="flex items-center gap-2">✓ Runtime Generation</li>
            </ul>
          </div>
        )}
      </div>

      <div className="w-full md:w-2/3 flex flex-col bg-white shadow rounded-lg overflow-hidden border border-gray-200">
        {data ? (
          <>
            <div className="flex flex-wrap border-b bg-gray-50 border-gray-200">
              {tabs.map(tab => (
                <button 
                  key={tab.key}
                  className={`px-4 py-3 text-sm font-medium transition-colors ${activeTab === tab.key ? 'bg-white border-b-2 border-blue-600 text-blue-600' : 'text-gray-500 hover:text-gray-800 hover:bg-gray-200'}`}
                  onClick={() => setActiveTab(tab.key)}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="p-4 overflow-auto flex-1 bg-white">
              <h2 className="text-xl font-bold mb-4 text-gray-800">{tabs.find(t => t.key === activeTab)?.label}</h2>
              {renderJsonViewer(activeTab === 'summary' ? null : data[activeTab as keyof CompileResponse])}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400 p-12 text-center bg-gray-50">
            <svg className="w-16 h-16 mb-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" /></svg>
            <p className="text-lg">Enter a prompt and click Generate</p>
            <p className="text-sm">Outputs will be visualized here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
