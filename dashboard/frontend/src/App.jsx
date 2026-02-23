import React, { useState, useEffect } from 'react'
import {
  Activity,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Target,
  Calendar,
  Zap,
  RefreshCw,
  Settings,
  Play,
  Clock,
  ChevronRight,
  BarChart3,
  TestTube,
  CheckCircle,
  XCircle,
  AlertCircle,
  Send,
  Timer,
  Database,
  MessageSquare,
} from 'lucide-react'
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'

// ============ Perry the Platypus Color Theme ============
const COLORS = {
  // Perry's body - teal/cyan
  primary: '#0D9488',
  primaryLight: '#14B8A6',
  primaryDark: '#0F766E',
  // Perry's beak/feet - orange
  accent: '#F97316',
  accentLight: '#FB923C',
  accentDark: '#EA580C',
  // Backgrounds - dark slate
  bgDark: '#0F172A',
  bgCard: '#1E293B',
  bgCardHover: '#334155',
  // Text
  textPrimary: '#F8FAFC',
  textSecondary: '#94A3B8',
  textMuted: '#64748B',
  // Status
  success: '#22C55E',
  danger: '#EF4444',
  warning: '#EAB308',
  info: '#3B82F6',
}

// ============ API Helpers ============

const API_BASE = '/api'

// Timezone helper - converts UTC to local time
function formatLocalTime(utcDate, options = {}) {
  if (!utcDate) return '-'
  try {
    const date = new Date(utcDate)
    const defaultOptions = {
      hour: '2-digit',
      minute: '2-digit',
      timeZoneName: 'short',
      ...options
    }
    return date.toLocaleString(undefined, defaultOptions)
  } catch {
    return '-'
  }
}

function formatLocalDate(utcDate) {
  if (!utcDate) return '-'
  try {
    const date = new Date(utcDate)
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    })
  } catch {
    return '-'
  }
}

function formatGameTime(utcDate) {
  if (!utcDate) return 'TBD'
  try {
    const date = new Date(utcDate)
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      timeZoneName: 'short'
    })
  } catch {
    return 'TBD'
  }
}

async function fetchAPI(endpoint, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(`API Error: ${response.status} - ${text}`)
    }
    const text = await response.text()
    return text ? JSON.parse(text) : null
  } catch (err) {
    if (err instanceof SyntaxError) {
      throw new Error('Invalid JSON response from server')
    }
    throw err
  }
}

// ============ Error Boundary ============

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('Error caught by boundary:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
          <div className="bg-slate-800 rounded-2xl border border-red-500/30 p-6 max-w-md w-full text-center">
            <div className="text-red-400 text-4xl mb-4">⚠️</div>
            <h2 className="text-xl font-bold text-white mb-2">Something went wrong</h2>
            <p className="text-slate-400 text-sm mb-4">
              An error occurred while rendering the dashboard.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-teal-500 text-white rounded-lg font-medium hover:bg-teal-400 transition-colors"
            >
              Reload Page
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

// ============ Modern Perry Components ============

function PerryButton({ children, onClick, disabled, primary, accent, className = '' }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        px-4 py-2 rounded-lg font-semibold text-sm
        transition-all duration-200 ease-in-out
        flex items-center gap-2
        ${disabled
          ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
          : primary
            ? 'bg-gradient-to-r from-teal-600 to-teal-500 text-white hover:from-teal-500 hover:to-teal-400 shadow-lg shadow-teal-500/25'
            : accent
              ? 'bg-gradient-to-r from-orange-500 to-orange-400 text-white hover:from-orange-400 hover:to-orange-300 shadow-lg shadow-orange-500/25'
              : 'bg-slate-700 text-slate-200 hover:bg-slate-600 border border-slate-600'
        }
        ${className}
      `}
    >
      {children}
    </button>
  )
}

function PerryPanel({ title, icon: Icon, children, className = '' }) {
  return (
    <div className={`bg-slate-800/50 backdrop-blur-sm rounded-2xl border border-slate-700/50 overflow-hidden ${className}`}>
      {title && (
        <div className="bg-gradient-to-r from-teal-600 to-teal-500 px-4 py-3 flex items-center gap-2">
          {Icon && <Icon size={18} className="text-white" />}
          <span className="text-white font-semibold">{title}</span>
        </div>
      )}
      <div className="p-4">
        {children}
      </div>
    </div>
  )
}

function PerryInput({ type = 'text', value, onChange, placeholder, className = '', label }) {
  return (
    <div className={className}>
      {label && <label className="block text-xs font-medium text-slate-400 mb-1">{label}</label>}
      <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        className="
          w-full px-3 py-2 rounded-lg
          bg-slate-900/50 border border-slate-600
          text-slate-100 placeholder-slate-500
          focus:outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500
          transition-colors
        "
      />
    </div>
  )
}

function PerrySelect({ value, onChange, children, className = '', label }) {
  return (
    <div className={className}>
      {label && <label className="block text-xs font-medium text-slate-400 mb-1">{label}</label>}
      <select
        value={value}
        onChange={onChange}
        className="
          w-full px-3 py-2 rounded-lg
          bg-slate-900/50 border border-slate-600
          text-slate-100
          focus:outline-none focus:border-teal-500 focus:ring-1 focus:ring-teal-500
          transition-colors
        "
      >
        {children}
      </select>
    </div>
  )
}

function StatusBadge({ status }) {
  // Normalize status to lowercase for comparison
  const normalizedStatus = (status || '').toString().toLowerCase()

  const config = {
    won: { bg: 'bg-green-500/20', text: 'text-green-400', border: 'border-green-500/30', label: 'WON' },
    lost: { bg: 'bg-red-500/20', text: 'text-red-400', border: 'border-red-500/30', label: 'LOST' },
    pending: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', border: 'border-yellow-500/30', label: 'PENDING' },
    correct: { bg: 'bg-green-500/20', text: 'text-green-400', border: 'border-green-500/30', label: 'CORRECT' },
    wrong: { bg: 'bg-red-500/20', text: 'text-red-400', border: 'border-red-500/30', label: 'WRONG' },
    push: { bg: 'bg-slate-500/20', text: 'text-slate-400', border: 'border-slate-500/30', label: 'PUSH' },
    posted: { bg: 'bg-blue-500/20', text: 'text-blue-400', border: 'border-blue-500/30', label: 'POSTED' },
    failed: { bg: 'bg-red-500/20', text: 'text-red-400', border: 'border-red-500/30', label: 'FAILED' },
  }
  const c = config[normalizedStatus] || config.pending
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${c.bg} ${c.text} border ${c.border}`}>
      {c.label}
    </span>
  )
}

function StatCard({ label, value, subvalue, trend, icon: Icon }) {
  return (
    <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-700/50">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">{label}</div>
          <div className="text-2xl font-bold text-white mt-1">{value}</div>
          {subvalue && <div className="text-xs text-slate-500 mt-1">{subvalue}</div>}
        </div>
        {Icon && (
          <div className="p-2 rounded-lg bg-teal-500/10">
            <Icon size={20} className="text-teal-400" />
          </div>
        )}
      </div>
      {trend !== undefined && (
        <div className={`mt-2 text-xs font-medium flex items-center gap-1 ${trend >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {trend >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
          {Math.abs(trend).toFixed(1)}%
        </div>
      )}
    </div>
  )
}

// ============ Live Bet Tracker Panel ============

function LiveBetTrackerPanel() {
  const [activeGames, setActiveGames] = useState([])
  const [allGames, setAllGames] = useState([])
  const [selectedGameId, setSelectedGameId] = useState('')
  const [selectedBetId, setSelectedBetId] = useState('')
  const [trackingData, setTrackingData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [alerts, setAlerts] = useState([])
  const [chartData, setChartData] = useState([])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  const fetchData = async () => {
    try {
      // Get today's date for filtering
      const today = new Date().toISOString().split('T')[0]

      const [activeData, alertsData, gamesData] = await Promise.all([
        fetchAPI('/live-tracking/active').catch(() => ({ active_games: [] })),
        fetchAPI('/live-tracking/alerts').catch(() => ({ alerts: [] })),
        fetchAPI(`/games?date=${today}&limit=100`).catch(() => [])
      ])
      // Filter active games to only show those that are NOT Final
      const filteredActive = (activeData.active_games || []).filter(g =>
        g.game_status && g.game_status !== 'Final' && !g.game_status.includes('Final')
      )
      setActiveGames(filteredActive)

      // Filter all games to only show today's games with predictions (for historical tracking)
      const gamesWithPredictions = (gamesData || []).filter(g =>
        g.game_status && (g.game_status.includes('Final') || g.period >= 3)
      )
      setAllGames(gamesWithPredictions)

      setAlerts(alertsData.alerts || [])
      setLoading(false)
    } catch (err) {
      console.error('Failed to fetch live tracking:', err)
      setLoading(false)
    }
  }

  // Load tracking data when game is selected
  useEffect(() => {
    if (selectedGameId) {
      fetchGameTracking(selectedGameId)
    }
  }, [selectedGameId])

  // Update chart when bet is selected
  useEffect(() => {
    if (trackingData && selectedBetId) {
      const rec = trackingData.recommendations?.find(r => r.recommendation_id === parseInt(selectedBetId))
      if (rec) {
        setChartData(prepareChartData(rec))
      }
    }
  }, [selectedBetId, trackingData])

  const fetchGameTracking = async (gameId) => {
    try {
      const data = await fetchAPI(`/live-tracking/recommendations/${gameId}`)
      setTrackingData(data)
      // Auto-select first bet if available
      if (data.recommendations?.length > 0 && !selectedBetId) {
        setSelectedBetId(data.recommendations[0].recommendation_id.toString())
      }
    } catch (err) {
      console.error('Failed to fetch game tracking:', err)
    }
  }

  const getProbabilityColor = (prob) => {
    if (prob >= 0.80) return 'text-green-400'
    if (prob >= 0.60) return 'text-teal-400'
    if (prob >= 0.40) return 'text-yellow-400'
    if (prob >= 0.20) return 'text-orange-400'
    return 'text-red-400'
  }

  const getProbabilityBg = (prob) => {
    if (prob >= 0.80) return 'bg-green-500/20 border-green-500/30'
    if (prob >= 0.60) return 'bg-teal-500/20 border-teal-500/30'
    if (prob >= 0.40) return 'bg-yellow-500/20 border-yellow-500/30'
    if (prob >= 0.20) return 'bg-orange-500/20 border-orange-500/30'
    return 'bg-red-500/20 border-red-500/30'
  }

  // Prepare chart data for a recommendation
  const prepareChartData = (rec) => {
    if (!rec || !rec.snapshots || rec.snapshots.length === 0) return []

    // Add initial probability as starting point
    const data = [{
      name: 'Halftime',
      probability: ((rec.initial_probability || 0.5) * 100).toFixed(1),
      time: 'Start',
      isInitial: true
    }]

    // Add all snapshots
    rec.snapshots.forEach((snap, i) => {
      data.push({
        name: `Q${snap.period} ${snap.clock}`,
        probability: (snap.live_probability * 100).toFixed(1),
        time: snap.created_at,
        alertSent: snap.alert_sent,
        alertType: snap.alert_type,
      })
    })

    return data
  }

  // Get selected bet info
  const selectedBet = trackingData?.recommendations?.find(r => r.recommendation_id === parseInt(selectedBetId))

  return (
    <PerryPanel title="Live Bet Tracker" icon={Activity}>
      {/* Active Alerts Banner */}
      {alerts.length > 0 && (
        <div className="mb-4 p-3 bg-orange-500/10 border border-orange-500/30 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle size={16} className="text-orange-400" />
            <span className="text-sm font-medium text-orange-400">
              {alerts.length} Active Alert{alerts.length !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="space-y-2 max-h-32 overflow-y-auto">
            {alerts.slice(0, 5).map((alert, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className={alert.alert_type === 'high_confidence' ? 'text-green-400' : 'text-red-400'}>
                  {alert.alert_type === 'high_confidence' ? '🎯' : '💰'}
                  {' '}{alert.pick} {alert.bet_type} ({(alert.live_probability * 100).toFixed(0)}%)
                </span>
                <span className="text-slate-500">{alert.game}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Game and Bet Selection */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        {/* Game Dropdown */}
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1">Select Game</label>
          <select
            value={selectedGameId}
            onChange={(e) => {
              setSelectedGameId(e.target.value)
              setSelectedBetId('') // Reset bet selection
            }}
            className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-600 text-slate-100 focus:outline-none focus:border-teal-500"
          >
            <option value="">-- Select a game --</option>
            <optgroup label="🔴 Live Games">
              {activeGames.map((game) => (
                <option key={game.game_id} value={game.game_id}>
                  {game.away_team} @ {game.home_team} (Q{game.period} {game.clock})
                </option>
              ))}
            </optgroup>
            <optgroup label="📋 Recent Games">
              {allGames.filter(g => !activeGames.find(ag => ag.game_id === g.id)).slice(0, 20).map((game) => (
                <option key={game.id} value={game.id}>
                  {game.away_team} @ {game.home_team} ({new Date(game.game_date).toLocaleDateString()})
                </option>
              ))}
            </optgroup>
          </select>
        </div>

        {/* Bet Dropdown */}
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1">Select Halftime Bet</label>
          <select
            value={selectedBetId}
            onChange={(e) => setSelectedBetId(e.target.value)}
            disabled={!trackingData?.recommendations?.length}
            className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-600 text-slate-100 focus:outline-none focus:border-teal-500 disabled:opacity-50"
          >
            <option value="">-- Select a bet --</option>
            {trackingData?.recommendations?.map((rec) => (
              <option key={rec.recommendation_id} value={rec.recommendation_id}>
                {rec.pick} {rec.bet_type} {rec.line} ({((rec.current_probability?.live_probability || rec.initial_probability || 0) * 100).toFixed(0)}%)
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Probability Chart */}
      {chartData.length > 0 && selectedBet && (
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <div>
              <span className="text-white font-medium">{selectedBet.pick}</span>
              <span className="text-slate-400 text-sm ml-2">
                {selectedBet.bet_type} {selectedBet.line}
              </span>
            </div>
            <div className={`px-3 py-1 rounded-lg border ${getProbabilityBg(selectedBet.current_probability?.live_probability || selectedBet.initial_probability)}`}>
              <span className={`text-lg font-bold ${getProbabilityColor(selectedBet.current_probability?.live_probability || selectedBet.initial_probability)}`}>
                {((selectedBet.current_probability?.live_probability || selectedBet.initial_probability || 0) * 100).toFixed(0)}%
              </span>
            </div>
          </div>

          {/* Large Chart */}
          <div className="h-64 bg-slate-900/50 rounded-lg border border-slate-700/50 p-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="probGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#14B8A6" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#14B8A6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="name"
                  tick={{ fill: '#64748B', fontSize: 11 }}
                  stroke="#334155"
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fill: '#64748B', fontSize: 11 }}
                  tickFormatter={(v) => `${v}%`}
                  stroke="#334155"
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1E293B',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    color: '#F8FAFC'
                  }}
                  formatter={(value, name, props) => {
                    const alertInfo = props.payload?.alertType ?
                      ` (${props.payload.alertType === 'high_confidence' ? '🎯 Alert Sent' : '💰 Cashout Alert'})` : ''
                    return [`${value}%${alertInfo}`, 'Probability']
                  }}
                />
                {/* Reference lines for thresholds */}
                <Line
                  type="monotone"
                  dataKey="probability"
                  stroke="#14B8A6"
                  strokeWidth={3}
                  dot={(props) => {
                    const { cx, cy, payload } = props
                    if (payload?.alertSent) {
                      return <circle cx={cx} cy={cy} r={6} fill={payload.alertType === 'high_confidence' ? '#22C55E' : '#EF4444'} />
                    }
                    if (payload?.isInitial) {
                      return <circle cx={cx} cy={cy} r={5} fill="#F97316" />
                    }
                    return <circle cx={cx} cy={cy} r={3} fill="#14B8A6" />
                  }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* Chart Legend */}
          <div className="flex flex-wrap gap-4 mt-2 text-xs text-slate-500">
            <div className="flex items-center gap-1">
              <span className="w-3 h-3 bg-orange-400 rounded-full"></span>
              Halftime (Initial)
            </div>
            <div className="flex items-center gap-1">
              <span className="w-3 h-3 bg-teal-400 rounded-full"></span>
              Snapshot
            </div>
            <div className="flex items-center gap-1">
              <span className="w-3 h-3 bg-green-400 rounded-full"></span>
              High Confidence Alert
            </div>
            <div className="flex items-center gap-1">
              <span className="w-3 h-3 bg-red-400 rounded-full"></span>
              Cashout Alert
            </div>
          </div>

          {/* Current Status */}
          {(selectedBet.current_probability?.live_probability >= 0.80 ||
            selectedBet.current_probability?.live_probability <= 0.20) && (
            <div className={`mt-3 p-3 rounded-lg ${
              selectedBet.current_probability?.live_probability >= 0.80
                ? 'bg-green-500/10 border border-green-500/30'
                : 'bg-red-500/10 border border-red-500/30'
            }`}>
              <div className={`flex items-center gap-2 ${
                selectedBet.current_probability?.live_probability >= 0.80 ? 'text-green-400' : 'text-red-400'
              }`}>
                {selectedBet.current_probability?.live_probability >= 0.80 ? (
                  <>
                    <CheckCircle size={16} />
                    <span className="font-medium">HIGH CONFIDENCE - Bet likely to hit!</span>
                  </>
                ) : (
                  <>
                    <AlertCircle size={16} />
                    <span className="font-medium">CASHOUT RECOMMENDED - Low probability</span>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* No Data State */}
      {selectedGameId && !trackingData?.recommendations?.length && (
        <div className="text-center text-slate-500 py-8">
          No halftime bets found for this game
        </div>
      )}

      {/* Legend */}
      <div className="flex flex-wrap gap-4 mt-3 text-xs text-slate-500">
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 bg-green-400 rounded-full"></span>
          80%+ High Confidence
        </div>
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 bg-yellow-400 rounded-full"></span>
          40-60% Uncertain
        </div>
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 bg-red-400 rounded-full"></span>
          20%- Cashout Zone
        </div>
      </div>
    </PerryPanel>
  )
}

// ============ Automated Reporting Panel ============

function AutomatedReportingPanel() {
  const [config, setConfig] = useState({
    daily_enabled: false,
    weekly_enabled: false,
    daily_time: '22:00',
    weekly_day: 'sunday',
    post_to_main: true,
    post_to_alerts: false,
  })
  const [saving, setSaving] = useState(false)
  const [lastReport, setLastReport] = useState(null)

  useEffect(() => {
    // Load config from localStorage (would be from API in production)
    const saved = localStorage.getItem('perrypicks_report_config')
    if (saved) {
      setConfig(JSON.parse(saved))
    }
  }, [])

  const saveConfig = async () => {
    setSaving(true)
    try {
      // Save to localStorage (would be API in production)
      localStorage.setItem('perrypicks_report_config', JSON.stringify(config))
      // Would call API to update backend scheduler
      await new Promise(resolve => setTimeout(resolve, 500))
    } catch (err) {
      console.error('Failed to save config:', err)
    }
    setSaving(false)
  }

  const testReport = async () => {
    try {
      // Post a test summary to Discord
      const summary = await fetchAPI('/summary/daily')
      if (summary) {
        // Would call a backend endpoint to post to Discord
        alert(`Test report generated for ${summary.date}:\n` +
          `${summary.predictions.total} predictions\n` +
          `${summary.predictions.winner_accuracy?.toFixed(0)}% accuracy\n` +
          `${summary.ghost_bets.profit_loss >= 0 ? '+' : ''}$${summary.ghost_bets.profit_loss.toFixed(2)} P/L`)
      }
    } catch (err) {
      alert('Failed to generate test report: ' + err.message)
    }
  }

  return (
    <PerryPanel title="Automated Reporting" icon={Calendar}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Daily Reports */}
        <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700/50">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-white">Daily Summary</span>
            <button
              onClick={() => setConfig({ ...config, daily_enabled: !config.daily_enabled })}
              className={`w-10 h-5 rounded-full transition-colors ${config.daily_enabled ? 'bg-teal-500' : 'bg-slate-600'}`}
            >
              <div className={`w-4 h-4 rounded-full bg-white transition-transform ${config.daily_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </div>
          {config.daily_enabled && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">Post at:</span>
                <input
                  type="time"
                  value={config.daily_time}
                  onChange={(e) => setConfig({ ...config, daily_time: e.target.value })}
                  className="px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-200 text-xs"
                />
                <span className="text-xs text-slate-500">CST</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.post_to_main}
                  onChange={(e) => setConfig({ ...config, post_to_main: e.target.checked })}
                  className="rounded bg-slate-700 border-slate-600"
                />
                <span className="text-xs text-slate-400">Post to Main channel</span>
              </div>
            </div>
          )}
        </div>

        {/* Weekly Reports */}
        <div className="bg-slate-900/50 rounded-lg p-4 border border-slate-700/50">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-white">Weekly Recap</span>
            <button
              onClick={() => setConfig({ ...config, weekly_enabled: !config.weekly_enabled })}
              className={`w-10 h-5 rounded-full transition-colors ${config.weekly_enabled ? 'bg-teal-500' : 'bg-slate-600'}`}
            >
              <div className={`w-4 h-4 rounded-full bg-white transition-transform ${config.weekly_enabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </div>
          {config.weekly_enabled && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">Day:</span>
                <select
                  value={config.weekly_day}
                  onChange={(e) => setConfig({ ...config, weekly_day: e.target.value })}
                  className="px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-200 text-xs"
                >
                  {['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'].map(day => (
                    <option key={day} value={day}>{day.charAt(0).toUpperCase() + day.slice(1)}</option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex justify-between items-center mt-4">
        <PerryButton onClick={testReport}>
          <Send size={14} />
          Test Report
        </PerryButton>
        <PerryButton primary onClick={saveConfig} disabled={saving}>
          {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle size={14} />}
          {saving ? 'Saving...' : 'Save Settings'}
        </PerryButton>
      </div>

      <div className="mt-3 text-xs text-slate-500">
        Reports will be automatically posted to Discord at the scheduled times.
        Requires backend scheduler to be running.
      </div>
    </PerryPanel>
  )
}

// ============ Odds Comparison Panel ============

function OddsComparisonPanel() {
  const [recommendations, setRecommendations] = useState([])
  const [loading, setLoading] = useState(true)
  const [minEdge, setMinEdge] = useState(0)

  useEffect(() => {
    fetchRecommendations()
  }, [])

  const fetchRecommendations = async () => {
    setLoading(true)
    try {
      // Fetch recent predictions and their recommendations
      const predictions = await fetchAPI('/predictions?limit=50')
      if (predictions && predictions.length > 0) {
        const allRecs = []
        for (const pred of predictions.slice(0, 20)) {
          try {
            const gameDetails = await fetchAPI(`/games/${pred.game_id}/details`)
            if (gameDetails.recommendations) {
              gameDetails.recommendations.forEach(rec => {
                allRecs.push({
                  ...rec,
                  game_id: pred.game_id,
                  prediction_id: pred.id,
                  pred_total: pred.pred_total,
                  pred_margin: pred.pred_margin,
                  home_win_prob: pred.home_win_prob,
                })
              })
            }
          } catch (e) {
            // Skip if can't fetch details
          }
        }
        setRecommendations(allRecs)
      }
    } catch (err) {
      console.error('Failed to fetch recommendations:', err)
    }
    setLoading(false)
  }

  // Filter by minimum edge
  const filteredRecs = recommendations.filter(rec =>
    (rec.edge || 0) >= minEdge / 100
  ).slice(0, 15)

  if (loading) {
    return (
      <PerryPanel title="Value Bets (Odds Comparison)" icon={Target}>
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={20} className="animate-spin text-teal-400" />
        </div>
      </PerryPanel>
    )
  }

  if (recommendations.length === 0) return null

  return (
    <PerryPanel title="Value Bets (Odds Comparison)" icon={Target}>
      <div className="flex justify-between items-center mb-3">
        <div className="text-xs text-slate-500">
          Model predictions vs market odds (highlighting edge)
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Min Edge:</span>
          <select
            value={minEdge}
            onChange={(e) => setMinEdge(parseInt(e.target.value))}
            className="px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-200 text-xs"
          >
            <option value={0}>All</option>
            <option value={2}>2%+</option>
            <option value={5}>5%+</option>
            <option value={10}>10%+</option>
          </select>
          <PerryButton onClick={fetchRecommendations}>
            <RefreshCw size={12} />
          </PerryButton>
        </div>
      </div>

      <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-48 overflow-y-auto">
        {filteredRecs.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50 sticky top-0">
              <tr>
                <th className="text-left p-2 text-slate-400 font-medium text-xs">Type</th>
                <th className="text-left p-2 text-slate-400 font-medium text-xs">Pick</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Model %</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Odds</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Edge</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Tier</th>
              </tr>
            </thead>
            <tbody>
              {filteredRecs.map((rec, i) => (
                <tr key={i} className="border-t border-slate-700/50 hover:bg-slate-800/30">
                  <td className="p-2 text-slate-400 uppercase text-xs">{rec.bet_type}</td>
                  <td className="p-2 text-slate-300 font-medium">{rec.pick}</td>
                  <td className="p-2 text-center text-slate-300">
                    {((rec.probability || 0) * 100).toFixed(0)}%
                  </td>
                  <td className="p-2 text-center text-slate-300">
                    {rec.odds > 0 ? `+${rec.odds}` : rec.odds}
                  </td>
                  <td className="p-2 text-center">
                    <span className={`font-medium ${
                      (rec.edge || 0) >= 0.10 ? 'text-green-400' :
                      (rec.edge || 0) >= 0.05 ? 'text-yellow-400' : 'text-slate-400'
                    }`}>
                      {((rec.edge || 0) * 100).toFixed(1)}%
                    </span>
                  </td>
                  <td className="p-2 text-center">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      rec.confidence_tier === 'A+' ? 'bg-green-500/20 text-green-400' :
                      rec.confidence_tier === 'A' ? 'bg-teal-500/20 text-teal-400' :
                      rec.confidence_tier === 'B+' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-slate-500/20 text-slate-400'
                    }`}>
                      {rec.confidence_tier || '-'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="p-4 text-center text-slate-500">
            No value bets found with {minEdge}%+ edge
          </div>
        )}
      </div>

      <div className="mt-2 text-xs text-slate-500">
        {filteredRecs.length} value bets • Edge = Model Probability - Implied Probability
      </div>
    </PerryPanel>
  )
}

// ============ Team Performance Panel ============

function TeamPerformancePanel() {
  const [teamStats, setTeamStats] = useState([])
  const [loading, setLoading] = useState(true)
  const [sortBy, setSortBy] = useState('accuracy')

  useEffect(() => {
    fetchTeamData()
  }, [])

  const fetchTeamData = async () => {
    setLoading(true)
    try {
      // Fetch games and predictions
      const [games, predictions] = await Promise.all([
        fetchAPI('/games?limit=200').catch(() => []),
        fetchAPI('/predictions?limit=200').catch(() => [])
      ])

      if (games.length > 0 && predictions.length > 0) {
        // Build team stats
        const teamMap = {}

        games.forEach(game => {
          const gamePreds = predictions.filter(p => p.game_id === game.id)
          if (gamePreds.length === 0) return

          // Home team
          if (!teamMap[game.home_team]) {
            teamMap[game.home_team] = { name: game.home_team_name || game.home_team, predictions: 0, correct: 0 }
          }
          // Away team
          if (!teamMap[game.away_team]) {
            teamMap[game.away_team] = { name: game.away_team_name || game.away_team, predictions: 0, correct: 0 }
          }

          gamePreds.forEach(pred => {
            teamMap[game.home_team].predictions++
            teamMap[game.away_team].predictions++
            if (pred.winner_correct === true || pred.status === 'correct') {
              teamMap[game.home_team].correct++
              teamMap[game.away_team].correct++
            }
          })
        })

        // Calculate accuracy and sort
        const teams = Object.values(teamMap)
          .filter(t => t.predictions > 0)
          .map(t => ({
            ...t,
            accuracy: t.predictions > 0 ? (t.correct / t.predictions * 100) : 0
          }))
          .sort((a, b) => {
            if (sortBy === 'accuracy') return b.accuracy - a.accuracy
            if (sortBy === 'predictions') return b.predictions - a.predictions
            return b.correct - a.correct
          })

        setTeamStats(teams)
      }
    } catch (err) {
      console.error('Failed to fetch team data:', err)
    }
    setLoading(false)
  }

  useEffect(() => {
    if (teamStats.length > 0) {
      fetchTeamData()
    }
  }, [sortBy])

  if (loading) {
    return (
      <PerryPanel title="Team Performance" icon={Target}>
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={20} className="animate-spin text-teal-400" />
        </div>
      </PerryPanel>
    )
  }

  if (teamStats.length === 0) return null

  return (
    <PerryPanel title="Team Performance" icon={Target}>
      <div className="flex justify-between items-center mb-3">
        <div className="text-xs text-slate-500">
          Accuracy by team (based on predictions involving each team)
        </div>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-200 text-xs"
        >
          <option value="accuracy">Sort by Accuracy</option>
          <option value="predictions">Sort by Volume</option>
        </select>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2 max-h-48 overflow-y-auto">
        {teamStats.slice(0, 15).map((team, i) => (
          <div
            key={team.name}
            className="bg-slate-900/50 rounded-lg p-2 border border-slate-700/50 text-center"
          >
            <div className="text-xs font-medium text-slate-300 truncate mb-1">{team.name}</div>
            <div className={`text-lg font-bold ${team.accuracy >= 60 ? 'text-green-400' : team.accuracy >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
              {team.accuracy.toFixed(0)}%
            </div>
            <div className="text-xs text-slate-500">
              {team.correct}/{team.predictions}
            </div>
          </div>
        ))}
      </div>
    </PerryPanel>
  )
}

// ============ Streak Tracker Panel ============

function StreakTrackerPanel() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStreakData()
  }, [])

  const fetchStreakData = async () => {
    setLoading(true)
    try {
      const predictions = await fetchAPI('/predictions?limit=200')
      if (predictions && predictions.length > 0) {
        // Calculate streaks
        let currentStreak = 0
        let currentStreakType = null
        let longestWinStreak = 0
        let longestLoseStreak = 0
        let tempWinStreak = 0
        let tempLoseStreak = 0

        // Sort by created_at descending (most recent first)
        const sorted = [...predictions].sort((a, b) =>
          new Date(b.created_at) - new Date(a.created_at)
        )

        // Find resolved predictions
        const resolved = sorted.filter(p => p.status === 'correct' || p.status === 'wrong' || p.winner_correct !== null)

        resolved.forEach((p, i) => {
          const isWin = p.winner_correct === true || p.status === 'correct'
          if (isWin) {
            tempWinStreak++
            tempLoseStreak = 0
            longestWinStreak = Math.max(longestWinStreak, tempWinStreak)
          } else {
            tempLoseStreak++
            tempWinStreak = 0
            longestLoseStreak = Math.max(longestLoseStreak, tempLoseStreak)
          }

          // Current streak (from most recent)
          if (i === 0) {
            currentStreakType = isWin ? 'win' : 'lose'
            currentStreak = 1
          } else if (currentStreakType === 'win' && isWin) {
            currentStreak++
          } else if (currentStreakType === 'lose' && !isWin) {
            currentStreak++
          }
        })

        // Best/worst days
        const byDate = {}
        predictions.forEach(p => {
          const date = new Date(p.created_at).toLocaleDateString()
          if (!byDate[date]) byDate[date] = { wins: 0, losses: 0 }
          if (p.winner_correct === true || p.status === 'correct') byDate[date].wins++
          else if (p.winner_correct === false || p.status === 'wrong') byDate[date].losses++
        })

        let bestDay = null
        let worstDay = null
        Object.entries(byDate).forEach(([date, { wins, losses }]) => {
          const net = wins - losses
          if (!bestDay || net > bestDay.net) bestDay = { date, wins, losses, net }
          if (!worstDay || net < worstDay.net) worstDay = { date, wins, losses, net }
        })

        setStats({
          currentStreak,
          currentStreakType,
          longestWinStreak,
          longestLoseStreak,
          bestDay,
          worstDay,
          totalResolved: resolved.length,
        })
      }
    } catch (err) {
      console.error('Failed to fetch streak data:', err)
    }
    setLoading(false)
  }

  if (loading) {
    return (
      <PerryPanel title="Streak Tracker" icon={TrendingUp}>
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={20} className="animate-spin text-teal-400" />
        </div>
      </PerryPanel>
    )
  }

  if (!stats) return null

  return (
    <PerryPanel title="Streak Tracker" icon={TrendingUp}>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Current Streak */}
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div className="text-xs text-slate-500 uppercase">Current Streak</div>
          <div className={`text-2xl font-bold ${stats.currentStreakType === 'win' ? 'text-green-400' : 'text-red-400'}`}>
            {stats.currentStreak > 0 && (
              <>
                {stats.currentStreakType === 'win' ? '🔥 ' : '❄️ '}
                {stats.currentStreak} {stats.currentStreakType}{stats.currentStreak !== 1 ? 's' : ''}
              </>
            )}
            {stats.currentStreak === 0 && '-'}
          </div>
        </div>

        {/* Longest Win Streak */}
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div className="text-xs text-slate-500 uppercase">Best Win Streak</div>
          <div className="text-2xl font-bold text-green-400">
            {stats.longestWinStreak > 0 ? `🔥 ${stats.longestWinStreak}` : '-'}
          </div>
        </div>

        {/* Longest Lose Streak */}
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div className="text-xs text-slate-500 uppercase">Worst Lose Streak</div>
          <div className="text-2xl font-bold text-red-400">
            {stats.longestLoseStreak > 0 ? `❄️ ${stats.longestLoseStreak}` : '-'}
          </div>
        </div>

        {/* Best Day */}
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div className="text-xs text-slate-500 uppercase">Best Day</div>
          {stats.bestDay ? (
            <>
              <div className="text-lg font-bold text-green-400">+{stats.bestDay.net}</div>
              <div className="text-xs text-slate-500">
                {stats.bestDay.wins}W-{stats.bestDay.losses}L
              </div>
            </>
          ) : (
            <div className="text-lg font-bold text-slate-500">-</div>
          )}
        </div>
      </div>

      {stats.totalResolved > 0 && (
        <div className="mt-3 text-xs text-slate-500 text-center">
          Based on {stats.totalResolved} resolved predictions
        </div>
      )}
    </PerryPanel>
  )
}

// ============ Pending Triggers Panel ============

function PendingTriggersPanel({ onRefresh }) {
  const [triggers, setTriggers] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchTriggers()
    const interval = setInterval(fetchTriggers, 30000) // Refresh every 30s
    return () => clearInterval(interval)
  }, [])

  const fetchTriggers = async () => {
    try {
      const data = await fetchAPI('/triggers/pending')
      setTriggers(data.triggers || [])
      setLoading(false)
    } catch (err) {
      console.error('Failed to fetch triggers:', err)
      setLoading(false)
    }
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'ready': return 'text-yellow-400 bg-yellow-500/20 border-yellow-500/30'
      case 'fired': return 'text-green-400 bg-green-500/20 border-green-500/30'
      default: return 'text-slate-400 bg-slate-500/20 border-slate-500/30'
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'ready': return '⏰'
      case 'fired': return '✅'
      default: return '⏳'
    }
  }

  // Group by status
  const pending = triggers.filter(t => t.trigger_status === 'pending')
  const ready = triggers.filter(t => t.trigger_status === 'ready')
  const fired = triggers.filter(t => t.trigger_status === 'fired')

  return (
    <PerryPanel title="Today's Games & Triggers" icon={Clock}>
      <div className="flex justify-between items-center mb-3">
        <div className="flex gap-4 text-xs">
          <span className="text-slate-400">
            <span className="text-yellow-400 font-bold">{ready.length}</span> ready
          </span>
          <span className="text-slate-400">
            <span className="text-slate-300 font-bold">{pending.length}</span> pending
          </span>
          <span className="text-slate-400">
            <span className="text-green-400 font-bold">{fired.length}</span> fired
          </span>
        </div>
        <PerryButton onClick={() => { fetchTriggers(); onRefresh && onRefresh(); }}>
          <RefreshCw size={14} />
        </PerryButton>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={20} className="animate-spin text-teal-400" />
        </div>
      ) : triggers.length > 0 ? (
        <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-64 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50 sticky top-0">
              <tr>
                <th className="text-left p-2 text-slate-400 font-medium text-xs">Game</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Status</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Score</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Trigger</th>
              </tr>
            </thead>
            <tbody>
              {triggers.map((t) => (
                <tr key={t.game_id} className="border-t border-slate-700/50 hover:bg-slate-800/30">
                  <td className="p-2">
                    <div className="text-slate-200">{t.away_team} @ {t.home_team}</div>
                    <div className="text-xs text-slate-500">
                      {t.game_status || 'Scheduled'}
                    </div>
                  </td>
                  <td className="p-2 text-center">
                    <span className={`px-2 py-1 rounded text-xs font-medium border ${getStatusColor(t.trigger_status)}`}>
                      {getStatusIcon(t.trigger_status)} {t.trigger_status}
                    </span>
                  </td>
                  <td className="p-2 text-center font-mono text-white">
                    {t.home_score} - {t.away_score}
                  </td>
                  <td className="p-2 text-center">
                    {t.prediction_id ? (
                      <span className="text-green-400 text-xs">#{t.prediction_id}</span>
                    ) : (
                      <span className="text-slate-500 text-xs">-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center text-slate-500 py-4">No games scheduled</div>
      )}
    </PerryPanel>
  )
}

// ============ Alert Panel ============

function AlertPanel() {
  const [alerts, setAlerts] = useState([])
  const [remedies, setRemedies] = useState({})
  const [loading, setLoading] = useState(true)
  const [executingAction, setExecutingAction] = useState(null)

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 60000) // Refresh every minute
    return () => clearInterval(interval)
  }, [])

  const fetchData = async () => {
    try {
      const [alertsData, remediesData] = await Promise.all([
        fetchAPI('/admin/alerts?count=20').catch(() => ({ alerts: [] })),
        fetchAPI('/admin/remedies').catch(() => ({ actions: [], description: {} }))
      ])
      setAlerts(alertsData.alerts || [])
      setRemedies(remediesData.description || {})
      setLoading(false)
    } catch (err) {
      console.error('Failed to fetch alerts:', err)
      setLoading(false)
    }
  }

  const executeRemedy = async (action) => {
    if (!confirm(`Execute remediation action: ${action}?`)) return
    setExecutingAction(action)
    try {
      await fetchAPI(`/admin/remedy/${action}`, { method: 'POST' })
      fetchData() // Refresh after action
    } catch (err) {
      alert(`Failed to execute ${action}: ${err.message}`)
    }
    setExecutingAction(null)
  }

  const getLevelColor = (level) => {
    switch (level) {
      case 'CRITICAL': return 'bg-red-500/20 text-red-400 border-red-500/30'
      case 'HIGH': return 'bg-orange-500/20 text-orange-400 border-orange-500/30'
      case 'MEDIUM': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
      default: return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
    }
  }

  const getLevelEmoji = (level) => {
    switch (level) {
      case 'CRITICAL': return '🚨'
      case 'HIGH': return '⚠️'
      case 'MEDIUM': return '⚡'
      default: return 'ℹ️'
    }
  }

  return (
    <PerryPanel title="System Alerts" icon={AlertCircle}>
      {/* Remediation Actions */}
      <div className="mb-4">
        <div className="text-xs text-slate-500 uppercase mb-2">Quick Actions</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(remedies).slice(0, 5).map(([action, description]) => (
            <button
              key={action}
              onClick={() => executeRemedy(action)}
              disabled={executingAction === action}
              className={`
                px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
                ${executingAction === action
                  ? 'bg-slate-600 text-slate-400 cursor-wait'
                  : 'bg-slate-700/50 text-slate-300 hover:bg-slate-600 hover:text-white border border-slate-600'
                }
              `}
              title={description}
            >
              {executingAction === action && <RefreshCw size={10} className="inline animate-spin mr-1" />}
              {action.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>

      {/* Recent Alerts */}
      <div className="text-xs text-slate-500 uppercase mb-2">Recent Alerts ({alerts.length})</div>
      <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-48 overflow-y-auto">
        {loading ? (
          <div className="p-4 text-center text-slate-400">
            <RefreshCw size={16} className="animate-spin inline" />
          </div>
        ) : alerts.length > 0 ? (
          <div className="divide-y divide-slate-700/50">
            {alerts.map((alert, i) => (
              <div key={i} className="p-3">
                <div className="flex items-start gap-2">
                  <span className="text-lg">{getLevelEmoji(alert.level)}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium border ${getLevelColor(alert.level)}`}>
                        {alert.level}
                      </span>
                      <span className="text-white font-medium text-sm">{alert.title}</span>
                    </div>
                    <div className="text-slate-400 text-xs">{alert.message}</div>
                    <div className="text-slate-500 text-xs mt-1">
                      {formatLocalTime(alert.timestamp, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </div>
                  </div>
                  {alert.remedy_available && (
                    <button
                      onClick={() => executeRemedy(alert.remedy_action)}
                      disabled={executingAction}
                      className="text-xs text-teal-400 hover:text-teal-300"
                    >
                      Fix
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-4 text-center text-slate-500">No alerts</div>
        )}
      </div>
    </PerryPanel>
  )
}

// ============ Prediction History Panel ============

function PredictionHistoryPanel({ onRefresh }) {
  const [predictions, setPredictions] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [triggerFilter, setTriggerFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    fetchPredictions()
  }, [])

  const fetchPredictions = async () => {
    setLoading(true)
    try {
      const data = await fetchAPI('/predictions?limit=100')
      setPredictions(data || [])
    } catch (err) {
      console.error('Failed to fetch predictions:', err)
    }
    setLoading(false)
  }

  // Filter predictions
  const filteredPredictions = predictions.filter(pred => {
    // Search filter - search in game info (would need game data)
    // For now, just filter by trigger type and status
    if (triggerFilter !== 'all' && pred.trigger_type !== triggerFilter) return false
    if (statusFilter !== 'all' && pred.status !== statusFilter) return false
    return true
  })

  const triggerTypes = [...new Set(predictions.map(p => p.trigger_type).filter(Boolean))]
  const statusTypes = [...new Set(predictions.map(p => p.status).filter(Boolean))]

  return (
    <PerryPanel title="Prediction History" icon={Target}>
      <div className="flex flex-wrap justify-between items-center gap-2 mb-4">
        <div className="flex flex-wrap gap-2">
          {/* Trigger Type Filter */}
          <select
            value={triggerFilter}
            onChange={(e) => setTriggerFilter(e.target.value)}
            className="px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-200 text-sm"
          >
            <option value="all">All Triggers</option>
            {triggerTypes.map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-200 text-sm"
          >
            <option value="all">All Status</option>
            {statusTypes.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-teal-400 hover:text-teal-300"
          >
            {expanded ? 'Collapse' : 'Expand'}
          </button>
          <PerryButton onClick={() => { fetchPredictions(); onRefresh && onRefresh(); }}>
            <RefreshCw size={14} />
          </PerryButton>
        </div>
      </div>

      {/* Results Count */}
      <div className="text-xs text-slate-500 mb-2">
        Showing {filteredPredictions.length} of {predictions.length} predictions
      </div>

      {/* Predictions Table */}
      <div className={`bg-slate-900/50 rounded-lg border border-slate-700/50 overflow-y-auto ${expanded ? 'max-h-96' : 'max-h-48'}`}>
        {loading ? (
          <div className="p-4 text-center text-slate-400">
            <RefreshCw size={16} className="animate-spin inline" />
          </div>
        ) : filteredPredictions.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50 sticky top-0">
              <tr>
                <th className="text-left p-2 text-slate-400 font-medium text-xs">Trigger</th>
                <th className="text-left p-2 text-slate-400 font-medium text-xs">Total</th>
                <th className="text-left p-2 text-slate-400 font-medium text-xs">Margin</th>
                <th className="text-left p-2 text-slate-400 font-medium text-xs">Win Prob</th>
                <th className="text-center p-2 text-slate-400 font-medium text-xs">Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredPredictions.slice(0, expanded ? 100 : 20).map((pred) => (
                <tr key={pred.id} className="border-t border-slate-700/50 hover:bg-slate-800/30">
                  <td className="p-2 text-slate-400 uppercase text-xs">{pred.trigger_type}</td>
                  <td className="p-2 text-slate-300">{pred.pred_total?.toFixed(1) || '-'}</td>
                  <td className="p-2 text-slate-300">{pred.pred_margin?.toFixed(1) || '-'}</td>
                  <td className="p-2 text-slate-300">{((pred.home_win_prob || 0) * 100).toFixed(0)}%</td>
                  <td className="p-2 text-center"><StatusBadge status={pred.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="p-4 text-center text-slate-500">No predictions found</div>
        )}
      </div>
    </PerryPanel>
  )
}

// ============ Panels ============

function PerformancePanel({ data, onRefresh, period: externalPeriod, onPeriodChange }) {
  const [period, setPeriod] = useState(externalPeriod || '30d')
  const [confidenceData, setConfidenceData] = useState([])
  const [showConfidenceChart, setShowConfidenceChart] = useState(false)

  // Fetch confidence distribution
  useEffect(() => {
    const fetchConfidence = async () => {
      try {
        const predictions = await fetchAPI('/predictions?limit=100')
        if (predictions && predictions.length > 0) {
          // Create histogram bins for win probability
          const bins = [
            { range: '0-20%', count: 0, color: COLORS.danger },
            { range: '20-40%', count: 0, color: COLORS.danger },
            { range: '40-50%', count: 0, color: COLORS.warning },
            { range: '50-60%', count: 0, color: COLORS.warning },
            { range: '60-70%', count: 0, color: COLORS.primary },
            { range: '70-80%', count: 0, color: COLORS.success },
            { range: '80-100%', count: 0, color: COLORS.success },
          ]
          predictions.forEach(p => {
            const prob = (p.home_win_prob || 0) * 100
            if (prob < 20) bins[0].count++
            else if (prob < 40) bins[1].count++
            else if (prob < 50) bins[2].count++
            else if (prob < 60) bins[3].count++
            else if (prob < 70) bins[4].count++
            else if (prob < 80) bins[5].count++
            else bins[6].count++
          })
          setConfidenceData(bins.filter(b => b.count > 0))
        }
      } catch (err) {
        console.error('Failed to fetch confidence data:', err)
      }
    }
    fetchConfidence()
  }, [period])

  const pieData = [
    { name: 'Correct', value: data?.correct_predictions || 0, color: COLORS.success },
    { name: 'Wrong', value: Math.max(0, (data?.total_predictions || 0) - (data?.correct_predictions || 0) - (data?.pending_predictions || 0)), color: COLORS.danger },
    { name: 'Pending', value: data?.pending_predictions || 0, color: COLORS.warning },
  ].filter(d => d.value > 0)

  return (
    <PerryPanel title="Performance Tracking" icon={BarChart3}>
      <div className="flex justify-between items-center mb-4">
        <div className="flex gap-2">
          {['7d', '30d', '90d', 'all'].map((p) => (
            <button
              key={p}
              onClick={() => {
                setPeriod(p)
                if (onPeriodChange) onPeriodChange(p)
              }}
              className={`
                px-3 py-1 rounded-lg text-sm font-medium transition-colors
                ${period === p
                  ? 'bg-teal-500 text-white'
                  : 'bg-slate-700/50 text-slate-400 hover:text-white hover:bg-slate-700'
                }
              `}
            >
              {p}
            </button>
          ))}
        </div>
        <PerryButton onClick={onRefresh}>
          <RefreshCw size={14} />
          Refresh
        </PerryButton>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard
          label="Correct"
          value={data?.correct_predictions || 0}
          icon={Target}
        />
        <StatCard
          label="Wrong"
          value={Math.max(0, (data?.total_predictions || 0) - (data?.correct_predictions || 0) - (data?.pending_predictions || 0))}
        />
        <StatCard
          label="Win Rate"
          value={`${data?.win_rate?.toFixed(1) || 0}%`}
        />
        <StatCard
          label="MAE"
          value={data?.total_mae?.toFixed(1) || '-'}
        />
      </div>

      {/* Chart */}
      <div className="h-40">
        {pieData.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={70}
                paddingAngle={3}
                dataKey="value"
                label={({ name, value }) => `${name}: ${value}`}
                labelLine={false}
              >
                {pieData.map((entry, index) => (
                  <Cell key={index} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1E293B',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  color: '#F8FAFC'
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full flex items-center justify-center text-slate-500">
            No prediction data yet
          </div>
        )}
      </div>

      {/* Confidence Distribution */}
      {confidenceData.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setShowConfidenceChart(!showConfidenceChart)}
            className="text-xs text-slate-400 hover:text-white mb-2 flex items-center gap-1"
          >
            <BarChart3 size={12} />
            {showConfidenceChart ? 'Hide' : 'Show'} Confidence Distribution
          </button>
          {showConfidenceChart && (
            <div className="h-32 bg-slate-900/50 rounded-lg border border-slate-700/50 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={confidenceData}>
                  <XAxis
                    dataKey="range"
                    tick={{ fill: '#64748B', fontSize: 9 }}
                  />
                  <YAxis
                    tick={{ fill: '#64748B', fontSize: 10 }}
                    allowDecimals={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1E293B',
                      border: '1px solid #334155',
                      borderRadius: '8px',
                      color: '#F8FAFC'
                    }}
                    formatter={(value) => [value, 'Predictions']}
                  />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {confidenceData.map((entry, index) => (
                      <Cell key={index} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </PerryPanel>
  )
}

function GhostBettorPanel({ stats, config, bets, onConfigSaved, onRefresh }) {
  const [editing, setEditing] = useState(false)
  const [formData, setFormData] = useState({})
  const [formErrors, setFormErrors] = useState({})
  const [bankrollHistory, setBankrollHistory] = useState([])
  const [showHistory, setShowHistory] = useState(false)

  // Fetch bankroll history
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const data = await fetchAPI('/ghost-bettor/bankroll-history?days=30')
        setBankrollHistory(data || [])
      } catch (err) {
        console.error('Failed to fetch bankroll history:', err)
      }
    }
    fetchHistory()
  }, [stats])

  useEffect(() => {
    if (config) {
      setFormData({
        starting_bankroll: config.starting_bankroll ?? 1000,
        default_bet_amount: config.default_bet_amount ?? 10,
        // Convert decimals to percentages (0.56 -> 56)
        total_min_prob: Math.round((config.total_min_prob ?? 0.55) * 100),
        spread_min_prob: Math.round((config.spread_min_prob ?? 0.55) * 100),
        ml_min_prob: Math.round((config.ml_min_prob ?? 0.60) * 100),
        is_active: config.is_active ?? false,
        reset_bankroll: false,
      })
    } else {
      // Default values when no config exists
      setFormData({
        starting_bankroll: 1000,
        default_bet_amount: 10,
        total_min_prob: 55,
        spread_min_prob: 55,
        ml_min_prob: 60,
        is_active: false,
        reset_bankroll: false,
      })
    }
  }, [config, editing])

  const handleSaveConfig = async () => {
    // Clear previous errors
    setFormErrors({})

    // Validation
    const errors = {}

    if (formData.starting_bankroll < 0) {
      errors.starting_bankroll = 'Bankroll must be positive'
    }

    if (formData.default_bet_amount < 0) {
      errors.default_bet_amount = 'Bet amount must be positive'
    }

    if (formData.default_bet_amount > formData.starting_bankroll) {
      errors.default_bet_amount = 'Bet amount cannot exceed bankroll'
    }

    if (formData.total_min_prob < 0 || formData.total_min_prob > 100) {
      errors.total_min_prob = 'Must be 0-100'
    }

    if (formData.spread_min_prob < 0 || formData.spread_min_prob > 100) {
      errors.spread_min_prob = 'Must be 0-100'
    }

    if (formData.ml_min_prob < 0 || formData.ml_min_prob > 100) {
      errors.ml_min_prob = 'Must be 0-100'
    }

    if (Object.keys(errors).length > 0) {
      setFormErrors(errors)
      return
    }

    try {
      const response = await fetchAPI('/ghost-bettor/config', {
        method: 'PUT',
        body: JSON.stringify({
          starting_bankroll: formData.starting_bankroll,
          default_bet_amount: formData.default_bet_amount,
          // Convert percentages back to decimals (56 -> 0.56)
          total_min_prob: (formData.total_min_prob || 0) / 100,
          spread_min_prob: (formData.spread_min_prob || 0) / 100,
          ml_min_prob: (formData.ml_min_prob || 0) / 100,
          is_active: formData.is_active,
          // If reset_bankroll is checked, set current_bankroll to starting_bankroll
          ...(formData.reset_bankroll ? { current_bankroll: formData.starting_bankroll } : {}),
        }),
      })
      // Close modal
      setEditing(false)
      setFormErrors({})
      // Update parent state with the new config
      await onConfigSaved(response)
    } catch (err) {
      setFormErrors({ submit: err.message })
    }
  }

  const profitLoss = stats?.profit_loss || 0
  const roi = stats?.roi || 0

  return (
    <PerryPanel title="Ghost Bettor" icon={DollarSign}>
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${config?.is_active ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`}></span>
          <span className={`text-sm font-medium ${config?.is_active ? 'text-green-400' : 'text-red-400'}`}>
            {config?.is_active ? 'ACTIVE' : 'PAUSED'}
          </span>
        </div>
        <div className="flex gap-2">
          <PerryButton onClick={onRefresh}>
            <RefreshCw size={14} />
            Refresh
          </PerryButton>
          <PerryButton accent onClick={() => setEditing(true)}>
            <Settings size={14} />
            Config
          </PerryButton>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatCard
          label="Bankroll"
          value={`$${(stats?.current_bankroll ?? config?.current_bankroll ?? 1000).toFixed(2)}`}
        />
        <StatCard
          label="P/L"
          value={`${profitLoss >= 0 ? '+' : ''}$${profitLoss.toFixed(2)}`}
          subvalue={`${roi.toFixed(1)}% ROI`}
          trend={roi}
        />
        <StatCard
          label="Win Rate"
          value={`${(stats?.win_rate ?? 0).toFixed(1)}%`}
          subvalue={`${stats?.won ?? 0}W - ${stats?.lost ?? 0}L`}
        />
        <StatCard
          label="Total Bets"
          value={stats?.total_bets ?? 0}
          subvalue={`${stats?.pending ?? 0} pending`}
        />
      </div>

      {/* Bankroll History Chart */}
      {bankrollHistory.length > 1 && (
        <div className="mb-4">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="text-xs text-slate-400 hover:text-white mb-2 flex items-center gap-1"
          >
            <BarChart3 size={12} />
            {showHistory ? 'Hide' : 'Show'} Bankroll History
          </button>
          {showHistory && (
            <div className="h-32 bg-slate-900/50 rounded-lg border border-slate-700/50 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={bankrollHistory}>
                  <defs>
                    <linearGradient id="bankrollGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#14B8A6" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#14B8A6" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="date"
                    tick={{ fill: '#64748B', fontSize: 10 }}
                    tickFormatter={(d) => new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  />
                  <YAxis
                    tick={{ fill: '#64748B', fontSize: 10 }}
                    tickFormatter={(v) => `$${v}`}
                    domain={['auto', 'auto']}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1E293B',
                      border: '1px solid #334155',
                      borderRadius: '8px',
                      color: '#F8FAFC'
                    }}
                    formatter={(value) => [`$${value.toFixed(2)}`, 'Bankroll']}
                    labelFormatter={(d) => new Date(d).toLocaleDateString()}
                  />
                  <Area
                    type="monotone"
                    dataKey="bankroll"
                    stroke="#14B8A6"
                    strokeWidth={2}
                    fill="url(#bankrollGradient)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* Recent Bets */}
      <div className="mt-4">
        <div className="text-sm font-medium text-slate-400 mb-2">Recent Bets</div>
        <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-36 overflow-y-auto">
          {bets && bets.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-slate-800/50 sticky top-0">
                <tr>
                  <th className="text-left p-2 text-slate-400 font-medium">Game</th>
                  <th className="text-left p-2 text-slate-400 font-medium">Type</th>
                  <th className="text-left p-2 text-slate-400 font-medium">Pick</th>
                  <th className="text-right p-2 text-slate-400 font-medium">$</th>
                  <th className="text-center p-2 text-slate-400 font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {bets.slice(0, 10).map((bet) => (
                  <tr key={bet.id} className="border-t border-slate-700/50 hover:bg-slate-800/30">
                    <td className="p-2 text-slate-300">{bet.game_id}</td>
                    <td className="p-2 text-slate-400 uppercase text-xs">{bet.bet_type}</td>
                    <td className="p-2 text-slate-300">{bet.pick}</td>
                    <td className="p-2 text-right text-slate-300">{bet.bet_amount?.toFixed(0)}</td>
                    <td className="p-2 text-center"><StatusBadge status={bet.result} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-6 text-center text-slate-500">No bets placed yet</div>
          )}
        </div>
      </div>

      {/* Config Modal */}
      {editing && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-2xl border border-slate-700 max-w-lg w-full mx-4 overflow-hidden">
            <div className="bg-gradient-to-r from-orange-500 to-orange-400 px-6 py-4 flex items-center gap-2">
              <Settings size={20} className="text-white" />
              <span className="text-white font-semibold">Ghost Bettor Configuration</span>
            </div>
            <div className="p-6 space-y-4">
              {/* Submit Error */}
              {formErrors.submit && (
                <div className="p-3 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm">
                  {formErrors.submit}
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <PerryInput
                    type="number"
                    label="Starting Bankroll ($)"
                    value={formData.starting_bankroll || ''}
                    onChange={(e) => setFormData({ ...formData, starting_bankroll: parseFloat(e.target.value) || 0 })}
                  />
                  {formErrors.starting_bankroll && (
                    <div className="text-xs text-red-400 mt-1">{formErrors.starting_bankroll}</div>
                  )}
                </div>
                <div>
                  <PerryInput
                    type="number"
                    label="Bet Amount ($)"
                    value={formData.default_bet_amount || ''}
                    onChange={(e) => setFormData({ ...formData, default_bet_amount: parseFloat(e.target.value) || 0 })}
                  />
                  {formErrors.default_bet_amount && (
                    <div className="text-xs text-red-400 mt-1">{formErrors.default_bet_amount}</div>
                  )}
                </div>
              </div>

              <div className="border-t border-slate-700 pt-4">
                <div className="text-sm font-medium text-slate-300 mb-3">Minimum Probability Thresholds (%)</div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <PerryInput
                      type="number"
                      label="Total"
                      value={formData.total_min_prob || ''}
                      onChange={(e) => setFormData({ ...formData, total_min_prob: parseInt(e.target.value) || 0 })}
                    />
                    {formErrors.total_min_prob && (
                      <div className="text-xs text-red-400 mt-1">{formErrors.total_min_prob}</div>
                    )}
                  </div>
                  <div>
                    <PerryInput
                      type="number"
                      label="Spread"
                      value={formData.spread_min_prob || ''}
                      onChange={(e) => setFormData({ ...formData, spread_min_prob: parseInt(e.target.value) || 0 })}
                    />
                    {formErrors.spread_min_prob && (
                      <div className="text-xs text-red-400 mt-1">{formErrors.spread_min_prob}</div>
                    )}
                  </div>
                  <div>
                    <PerryInput
                      type="number"
                      label="Moneyline"
                      value={formData.ml_min_prob || ''}
                      onChange={(e) => setFormData({ ...formData, ml_min_prob: parseInt(e.target.value) || 0 })}
                    />
                    {formErrors.ml_min_prob && (
                      <div className="text-xs text-red-400 mt-1">{formErrors.ml_min_prob}</div>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <button
                  onClick={() => setFormData({ ...formData, is_active: !formData.is_active })}
                  className={`w-12 h-6 rounded-full transition-colors ${formData.is_active ? 'bg-teal-500' : 'bg-slate-600'}`}
                >
                  <div className={`w-5 h-5 rounded-full bg-white transition-transform ${formData.is_active ? 'translate-x-6' : 'translate-x-0.5'}`}></div>
                </button>
                <span className="text-sm text-slate-300">Active (auto-place qualifying bets)</span>
              </div>

              <div className="flex items-center gap-3 pt-2 border-t border-slate-700">
                <button
                  onClick={() => setFormData({ ...formData, reset_bankroll: !formData.reset_bankroll })}
                  className={`w-12 h-6 rounded-full transition-colors ${formData.reset_bankroll ? 'bg-orange-500' : 'bg-slate-600'}`}
                >
                  <div className={`w-5 h-5 rounded-full bg-white transition-transform ${formData.reset_bankroll ? 'translate-x-6' : 'translate-x-0.5'}`}></div>
                </button>
                <span className="text-sm text-slate-300">Reset bankroll to starting amount (${formData.starting_bankroll})</span>
              </div>
            </div>
            <div className="px-6 py-4 bg-slate-900/50 flex justify-end gap-3">
              <PerryButton onClick={() => setEditing(false)}>Cancel</PerryButton>
              <PerryButton primary onClick={handleSaveConfig}>Save Configuration</PerryButton>
            </div>
          </div>
        </div>
      )}
    </PerryPanel>
  )
}

function ManualPredictionPanel({ onPredictionMade }) {
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0])
  const [games, setGames] = useState([])
  const [selectedGame, setSelectedGame] = useState('')
  const [triggerType, setTriggerType] = useState('halftime')
  const [loading, setLoading] = useState(false)
  const [loadingGames, setLoadingGames] = useState(false)
  const [result, setResult] = useState(null)

  const fetchGames = async (date) => {
    setLoadingGames(true)
    setSelectedGame('')
    try {
      const data = await fetchAPI(`/schedule/${date}`)
      setGames(data.games || [])
    } catch (err) {
      console.error('Failed to fetch games:', err)
      setGames([])
    }
    setLoadingGames(false)
  }

  useEffect(() => {
    fetchGames(selectedDate)
  }, [selectedDate])

  const handlePredict = async () => {
    if (!selectedGame) return
    setLoading(true)
    setResult(null)
    try {
      const res = await fetchAPI('/predictions/manual', {
        method: 'POST',
        body: JSON.stringify({
          game_id: selectedGame,
          trigger_type: triggerType,
          post_to_discord: false,
        }),
      })
      setResult(res)
      if (onPredictionMade) onPredictionMade()
    } catch (err) {
      setResult({ error: err.message })
    }
    setLoading(false)
  }

  const handleSlatePredict = async () => {
    setLoading(true)
    setResult(null)
    try {
      const res = await fetchAPI(`/predictions/slate?date=${selectedDate}`)
      setResult(res)
      if (onPredictionMade) onPredictionMade()
    } catch (err) {
      setResult({ error: err.message })
    }
    setLoading(false)
  }

  return (
    <PerryPanel title="Manual Prediction" icon={Zap}>
      <div className="grid grid-cols-3 gap-4 mb-4">
        <PerryInput
          type="date"
          label="Date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
        />
        <PerrySelect
          label="Game"
          value={selectedGame}
          onChange={(e) => setSelectedGame(e.target.value)}
          disabled={loadingGames || games.length === 0}
        >
          <option value="">{loadingGames ? 'Loading...' : 'Select game...'}</option>
          {games.map((game) => (
            <option key={game.nba_id} value={game.nba_id}>
              {game.away_team} @ {game.home_team}
            </option>
          ))}
        </PerrySelect>
        <PerrySelect
          label="Trigger"
          value={triggerType}
          onChange={(e) => setTriggerType(e.target.value)}
        >
          <option value="halftime">Halftime (H1 scores needed)</option>
          {/* Other trigger types not yet supported by backend */}
        </PerrySelect>
      </div>

      <div className="flex gap-3 mb-4">
        <PerryButton
          onClick={handlePredict}
          disabled={!selectedGame || loading}
          primary
        >
          {loading ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
          Run Prediction
        </PerryButton>
        <PerryButton onClick={handleSlatePredict} disabled={loading || games.length === 0}>
          <Calendar size={14} />
          Run Full Slate ({games.length} games)
        </PerryButton>
      </div>

      {/* Game List */}
      {games.length > 0 && (
        <div className="mb-4">
          <div className="text-sm font-medium text-slate-400 mb-2">
            {games.length} games on {selectedDate}
          </div>
          <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-28 overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {games.map((game) => (
                  <tr
                    key={game.nba_id}
                    onClick={() => setSelectedGame(game.nba_id)}
                    className={`
                      cursor-pointer border-t border-slate-700/50 first:border-t-0
                      ${selectedGame === game.nba_id
                        ? 'bg-teal-500/20 text-teal-300'
                        : 'hover:bg-slate-800/50 text-slate-300'
                      }
                    `}
                  >
                    <td className="p-2">{game.away_team} @ {game.home_team}</td>
                    <td className="p-2 text-right text-slate-500">{game.game_status || 'Scheduled'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 p-4">
          {result.error ? (
            <div className="text-red-400 flex items-center gap-2">
              <span className="text-lg">✗</span>
              {result.error}
            </div>
          ) : (
            <div>
              <div className="text-green-400 font-medium mb-2 flex items-center gap-2">
                <span className="text-lg">✓</span>
                Prediction Complete
              </div>
              {result.prediction && (
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <div className="text-slate-500">Pred Total</div>
                    <div className="text-white font-semibold">{result.prediction.pred_final_total?.toFixed(1)}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Pred Margin</div>
                    <div className="text-white font-semibold">{result.prediction.pred_final_margin?.toFixed(1)}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Win Prob</div>
                    <div className="text-white font-semibold">{((result.prediction.home_win_prob || 0) * 100).toFixed(1)}%</div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </PerryPanel>
  )
}

function OperationsPanel({ games, predictions, onRefresh }) {
  const [liveGames, setLiveGames] = useState([])
  const [lastLiveUpdate, setLastLiveUpdate] = useState(null)

  // Fast polling for live games (every 10 seconds)
  useEffect(() => {
    const fetchLiveScores = async () => {
      try {
        const data = await fetchAPI('/live/scores')
        const games = data?.games || []
        // Filter to only show in-progress games
        const inProgress = games.filter(g =>
          g.status !== 'Scheduled' && g.status !== 'Final' && g.period > 0
        )
        setLiveGames(inProgress)
        setLastLiveUpdate(new Date().toLocaleTimeString())
      } catch (err) {
        console.error('Failed to fetch live scores:', err)
      }
    }

    fetchLiveScores()
    const interval = setInterval(fetchLiveScores, 10000) // 10 second refresh for live games
    return () => clearInterval(interval)
  }, [])

  // Merge live games with provided games
  const allGames = [...(games || [])]
  const activeGames = allGames.filter(g =>
    g.status !== 'Scheduled' || g.home_score > 0 || g.away_score > 0
  )

  // Prioritize live games
  const displayGames = liveGames.length > 0 ? liveGames : activeGames

  // Format the status for display
  const formatGameStatus = (game) => {
    const status = game.status || 'Scheduled'
    if (status === 'Final') return 'Final'
    if (status === 'Halftime') return 'Halftime'
    if (status === 'Scheduled') return 'Scheduled'
    // Status may already contain period info like "1:26 - 2nd"
    if (status.includes(' - ')) return status
    // Build from period/clock if available
    if (game.period && game.period > 0) {
      const periodName = game.period <= 4 ? `Q${game.period}` : `OT${game.period - 4}`
      if (game.clock) return `${game.clock} - ${periodName}`
      return periodName
    }
    return status
  }

  return (
    <PerryPanel title="Operations Center" icon={Activity}>
      <div className="flex justify-between items-center mb-4">
        <div className="text-xs text-slate-500">
          {lastLiveUpdate && <span>Live update: {lastLiveUpdate}</span>}
        </div>
        <PerryButton onClick={onRefresh}>
          <RefreshCw size={14} />
          Refresh
        </PerryButton>
      </div>

      {/* Live Games */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-2">
          {liveGames.length > 0 ? (
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
              <span className="text-sm font-medium text-green-400">LIVE ({liveGames.length})</span>
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 bg-slate-400 rounded-full"></span>
              <span className="text-sm font-medium text-slate-400">No Live Games</span>
            </span>
          )}
        </div>
        <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-40 overflow-y-auto">
          {displayGames.length > 0 ? (
            <div className="divide-y divide-slate-700/50">
              {displayGames.map((game, i) => (
                <div key={i} className="p-2 flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-slate-300 truncate">
                      {game.away} @ {game.home}
                    </div>
                    <div className="text-xs text-teal-400 mt-0.5 font-medium">
                      {formatGameStatus(game)}
                    </div>
                  </div>
                  <div className="text-right ml-2 flex-shrink-0">
                    <div className="text-lg font-bold text-white">
                      {game.away_score} - {game.home_score}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-4 text-center text-slate-500">No live games</div>
          )}
        </div>
      </div>

      {/* Recent Predictions */}
      <div>
        <div className="text-sm font-medium text-slate-400 mb-2">
          Recent Predictions ({predictions?.length || 0})
        </div>
        <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-32 overflow-y-auto">
          {predictions && predictions.length > 0 ? (
            <table className="w-full text-sm">
              <tbody>
                {predictions.slice(0, 10).map((pred) => (
                  <tr key={pred.id} className="border-t border-slate-700/50 first:border-t-0">
                    <td className="p-2 text-slate-400 uppercase text-xs">{pred.trigger_type}</td>
                    <td className="p-2 text-slate-300">Total: {pred.pred_total?.toFixed(0)}</td>
                    <td className="p-2 text-slate-300">Margin: {pred.pred_margin?.toFixed(1)}</td>
                    <td className="p-2 text-center"><StatusBadge status={pred.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-4 text-center text-slate-500">No predictions yet</div>
          )}
        </div>
      </div>
    </PerryPanel>
  )
}

// ============ Game Detail Modal ============

function GameDetailModal({ gameId, onClose }) {
  const [details, setDetails] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchDetails = async () => {
    if (!gameId) return
    setLoading(true)
    setError(null)
    try {
      const data = await fetchAPI(`/games/${gameId}/details`)
      setDetails(data)
    } catch (err) {
      setError(err.message || 'Failed to load game details')
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchDetails()
  }, [gameId])

  if (!gameId) return null

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-slate-800 rounded-2xl border border-slate-700 max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden" onClick={e => e.stopPropagation()}>
        {loading ? (
          <div className="p-8 flex items-center justify-center">
            <RefreshCw size={24} className="animate-spin text-teal-400" />
          </div>
        ) : error ? (
          <div className="p-8">
            <div className="text-center">
              <div className="text-red-400 text-4xl mb-4">⚠️</div>
              <h2 className="text-xl font-bold text-white mb-2">Error Loading Game</h2>
              <p className="text-slate-400 text-sm mb-4">{error}</p>
              <div className="flex gap-3 justify-center">
                <PerryButton onClick={fetchDetails}>
                  <RefreshCw size={14} />
                  Retry
                </PerryButton>
                <PerryButton onClick={onClose}>
                  Close
                </PerryButton>
              </div>
            </div>
          </div>
        ) : details ? (
          <div className="p-8 flex items-center justify-center">
            <RefreshCw size={24} className="animate-spin text-teal-400" />
          </div>
        ) : details ? (
          <>
            {/* Header */}
            <div className="bg-gradient-to-r from-teal-600 to-teal-500 px-6 py-4">
              <div className="flex justify-between items-start">
                <div>
                  <h2 className="text-xl font-bold text-white">
                    {details.game.away_team_name || details.game.away_team} @ {details.game.home_team_name || details.game.home_team}
                  </h2>
                  <p className="text-teal-100 text-sm">{formatLocalDate(details.game.game_date)}</p>
                </div>
                <button onClick={onClose} className="text-white/80 hover:text-white">
                  ✕
                </button>
              </div>
              {/* Score */}
              {details.game.final_home_score !== null && (
                <div className="mt-3 text-2xl font-bold text-white">
                  {details.game.final_away_score} - {details.game.final_home_score}
                  <span className="text-sm font-normal text-teal-100 ml-2">Final</span>
                </div>
              )}
            </div>

            <div className="p-6 overflow-y-auto max-h-[60vh] space-y-4">
              {/* Predictions */}
              <div>
                <h3 className="text-sm font-semibold text-slate-300 mb-2 uppercase tracking-wide">Predictions</h3>
                {details.predictions.length > 0 ? (
                  <div className="space-y-2">
                    {details.predictions.map((pred) => (
                      <div key={pred.id} className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
                        <div className="flex justify-between items-center mb-2">
                          <span className="text-xs font-medium text-teal-400 uppercase">{pred.trigger_type}</span>
                          <StatusBadge status={pred.status} />
                        </div>
                        <div className="grid grid-cols-4 gap-2 text-sm">
                          <div>
                            <div className="text-slate-500 text-xs">Pred Total</div>
                            <div className="text-white font-medium">{pred.pred_total?.toFixed(1)}</div>
                          </div>
                          <div>
                            <div className="text-slate-500 text-xs">Actual</div>
                            <div className="text-white font-medium">{pred.actual_total?.toFixed(1) || '-'}</div>
                          </div>
                          <div>
                            <div className="text-slate-500 text-xs">Pred Margin</div>
                            <div className="text-white font-medium">{pred.pred_margin?.toFixed(1)}</div>
                          </div>
                          <div>
                            <div className="text-slate-500 text-xs">Win Prob</div>
                            <div className="text-white font-medium">{((pred.home_win_prob || 0) * 100).toFixed(0)}%</div>
                          </div>
                        </div>
                        {pred.h1_home !== null && (
                          <div className="mt-2 text-xs text-slate-500">Halftime: {pred.h1_away} - {pred.h1_home}</div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-slate-500 text-sm">No predictions yet</div>
                )}
              </div>

              {/* Recommendations */}
              {details.recommendations.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-300 mb-2 uppercase tracking-wide">Betting Recommendations</h3>
                  <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-800/50">
                        <tr>
                          <th className="text-left p-2 text-slate-400 font-medium">Type</th>
                          <th className="text-left p-2 text-slate-400 font-medium">Pick</th>
                          <th className="text-left p-2 text-slate-400 font-medium">Odds</th>
                          <th className="text-left p-2 text-slate-400 font-medium">Tier</th>
                        </tr>
                      </thead>
                      <tbody>
                        {details.recommendations.map((rec) => (
                          <tr key={rec.id} className="border-t border-slate-700/50">
                            <td className="p-2 text-slate-300 uppercase text-xs">{rec.bet_type}</td>
                            <td className="p-2 text-white">{rec.pick}</td>
                            <td className="p-2 text-slate-300">{rec.odds}</td>
                            <td className="p-2">
                              <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                                rec.confidence_tier === 'A+' ? 'bg-green-500/20 text-green-400' :
                                rec.confidence_tier === 'A' ? 'bg-teal-500/20 text-teal-400' :
                                rec.confidence_tier === 'B+' ? 'bg-yellow-500/20 text-yellow-400' :
                                'bg-slate-500/20 text-slate-400'
                              }`}>
                                {rec.confidence_tier}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Ghost Bets */}
              {details.ghost_bets.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-300 mb-2 uppercase tracking-wide">Ghost Bets</h3>
                  <div className="space-y-2">
                    {details.ghost_bets.map((bet) => (
                      <div key={bet.id} className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50 flex justify-between items-center">
                        <div>
                          <span className="text-white font-medium">{bet.pick}</span>
                          <span className="text-slate-400 text-sm ml-2">(${bet.bet_amount})</span>
                        </div>
                        <StatusBadge status={bet.result} />
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="p-8 text-center text-slate-400">Game not found</div>
        )}
      </div>
    </div>
  )
}

// ============ Daily Summary Panel ============

function DailySummaryPanel({ date }) {
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const dateStr = date || new Date().toISOString().split('T')[0]
    fetchAPI(`/summary/daily?date=${dateStr}`)
      .then(setSummary)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [date])

  if (loading) {
    return (
      <PerryPanel title="Daily Summary" icon={Calendar}>
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={20} className="animate-spin text-teal-400" />
        </div>
      </PerryPanel>
    )
  }

  if (!summary) return null

  return (
    <PerryPanel title={`Daily Summary - ${summary.date}`} icon={Calendar}>
      {/* Top Row - Games, Winner Accuracy, Ghost Bets */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
        {/* Games */}
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div className="text-xs text-slate-500 uppercase">Games</div>
          <div className="text-2xl font-bold text-white">{summary.games.monitored}</div>
          <div className="text-xs text-slate-400">{summary.games.final} final</div>
        </div>

        {/* Winner Accuracy */}
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div className="text-xs text-slate-500 uppercase">Winner Accuracy</div>
          <div className="text-2xl font-bold text-white">{summary.predictions.winner_accuracy?.toFixed(0) || 0}%</div>
          <div className="text-xs text-slate-400">
            {summary.predictions.winner_correct || 0}W - {summary.predictions.winner_wrong || 0}L
          </div>
        </div>

        {/* Ghost Bets */}
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div className="text-xs text-slate-500 uppercase">Ghost Bets</div>
          <div className="text-2xl font-bold text-white">{summary.ghost_bets.total}</div>
          <div className={`text-xs ${summary.ghost_bets.profit_loss >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {summary.ghost_bets.profit_loss >= 0 ? '+' : ''}${summary.ghost_bets.profit_loss.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Bet Type Breakdown */}
      {summary.by_bet_type && (
        <div className="mb-4">
          <div className="text-xs text-slate-500 uppercase mb-2">By Bet Type (Recommendations)</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {/* Totals */}
            <div className="bg-slate-900/30 rounded-lg p-3 border border-slate-700/30">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-teal-400 font-semibold text-sm">TOTALS</span>
                <span className="text-xs text-slate-500">(O/U)</span>
              </div>
              <div className="text-lg font-bold text-white">{summary.by_bet_type.total.total}</div>
              <div className="flex gap-2 text-xs mt-1">
                <span className="text-green-400">{summary.by_bet_type.total.won}W</span>
                <span className="text-red-400">{summary.by_bet_type.total.lost}L</span>
                <span className="text-yellow-400">{summary.by_bet_type.total.pending}P</span>
              </div>
              {summary.by_bet_type.total.total > 0 && (
                <div className={`text-xs mt-1 ${summary.by_bet_type.total.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                  {summary.by_bet_type.total.win_rate.toFixed(0)}% win rate
                </div>
              )}
            </div>

            {/* Spreads */}
            <div className="bg-slate-900/30 rounded-lg p-3 border border-slate-700/30">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-orange-400 font-semibold text-sm">SPREADS</span>
              </div>
              <div className="text-lg font-bold text-white">{summary.by_bet_type.spread.total}</div>
              <div className="flex gap-2 text-xs mt-1">
                <span className="text-green-400">{summary.by_bet_type.spread.won}W</span>
                <span className="text-red-400">{summary.by_bet_type.spread.lost}L</span>
                <span className="text-yellow-400">{summary.by_bet_type.spread.pending}P</span>
              </div>
              {summary.by_bet_type.spread.total > 0 && (
                <div className={`text-xs mt-1 ${summary.by_bet_type.spread.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                  {summary.by_bet_type.spread.win_rate.toFixed(0)}% win rate
                </div>
              )}
            </div>

            {/* Moneylines */}
            <div className="bg-slate-900/30 rounded-lg p-3 border border-slate-700/30">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-purple-400 font-semibold text-sm">MONEYLINE</span>
              </div>
              <div className="text-lg font-bold text-white">{summary.by_bet_type.moneyline.total}</div>
              <div className="flex gap-2 text-xs mt-1">
                <span className="text-green-400">{summary.by_bet_type.moneyline.won}W</span>
                <span className="text-red-400">{summary.by_bet_type.moneyline.lost}L</span>
                <span className="text-yellow-400">{summary.by_bet_type.moneyline.pending}P</span>
              </div>
              {summary.by_bet_type.moneyline.total > 0 && (
                <div className={`text-xs mt-1 ${summary.by_bet_type.moneyline.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                  {summary.by_bet_type.moneyline.win_rate.toFixed(0)}% win rate
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* By Trigger Type */}
      <div className="text-xs text-slate-500 uppercase mb-2">By Trigger Type</div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {Object.entries(summary.by_trigger_type).map(([type, data]) => (
          <div key={type} className="bg-slate-900/30 rounded p-2 text-center">
            <div className="text-xs text-slate-400 uppercase">{type.replace('_', ' ')}</div>
            <div className="text-white font-medium">{data.total}</div>
            {data.total > 0 && (
              <div className="text-xs text-green-400">{data.winner_correct || data.correct || 0} correct</div>
            )}
          </div>
        ))}
      </div>

      {/* MAE Stats */}
      {summary.predictions.total_mae && (
        <div className="mt-3 pt-3 border-t border-slate-700 text-xs text-slate-500">
          Total MAE: <span className="text-slate-300">{summary.predictions.total_mae.toFixed(2)}</span>
          {summary.predictions.margin_mae && (
            <span className="ml-3">Margin MAE: <span className="text-slate-300">{summary.predictions.margin_mae.toFixed(2)}</span></span>
          )}
        </div>
      )}
    </PerryPanel>
  )
}

// ============ Trigger Config Panel ============

function TriggerConfigPanel({ onConfigChange }) {
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const fetchConfig = async () => {
    setLoading(true)
    try {
      const data = await fetchAPI('/system/config')
      setConfig(data)
    } catch (err) {
      console.error('Failed to fetch config:', err)
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchConfig()
  }, [])

  const toggleTrigger = async (key) => {
    if (!config) return
    setSaving(true)
    try {
      const newConfig = { ...config, [key]: !config[key] }
      const result = await fetchAPI('/system/config', {
        method: 'PUT',
        body: JSON.stringify({ [key]: !config[key] }),
      })
      setConfig(result)
      if (onConfigChange) onConfigChange(result)
    } catch (err) {
      console.error('Failed to update config:', err)
    }
    setSaving(false)
  }

  if (loading) {
    return (
      <PerryPanel title="Trigger Settings" icon={Settings}>
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={20} className="animate-spin text-teal-400" />
        </div>
      </PerryPanel>
    )
  }

  if (!config) return null

  const triggers = [
    { key: 'pregame_enabled', label: 'Pregame', desc: 'Before tip-off' },
    { key: 'halftime_enabled', label: 'Halftime', desc: 'At the half' },
    { key: 'q3_5min_enabled', label: 'Q3 (5 min)', desc: 'Late 3rd quarter' },
  ]

  return (
    <PerryPanel title="Trigger Settings" icon={Settings}>
      <div className="space-y-3">
        {triggers.map((trigger) => (
          <div key={trigger.key} className="flex items-center justify-between bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
            <div>
              <div className="text-white font-medium">{trigger.label}</div>
              <div className="text-xs text-slate-500">{trigger.desc}</div>
            </div>
            <button
              onClick={() => toggleTrigger(trigger.key)}
              disabled={saving}
              className={`w-12 h-6 rounded-full transition-colors ${
                config[trigger.key] ? 'bg-teal-500' : 'bg-slate-600'
              }`}
            >
              <div className={`w-5 h-5 rounded-full bg-white transition-transform ${
                config[trigger.key] ? 'translate-x-6' : 'translate-x-0.5'
              }`} />
            </button>
          </div>
        ))}

        {/* Odds Fetch Toggle */}
        <div className="flex items-center justify-between bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
          <div>
            <div className="text-white font-medium">Odds Fetching</div>
            <div className="text-xs text-slate-500">Pull odds when triggers fire</div>
          </div>
          <button
            onClick={() => toggleTrigger('odds_fetch_enabled')}
            disabled={saving}
            className={`w-12 h-6 rounded-full transition-colors ${
              config.odds_fetch_enabled ? 'bg-orange-500' : 'bg-slate-600'
            }`}
          >
            <div className={`w-5 h-5 rounded-full bg-white transition-transform ${
              config.odds_fetch_enabled ? 'translate-x-6' : 'translate-x-0.5'
            }`} />
          </button>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-slate-700 text-xs text-slate-500">
        Disabled triggers will not queue predictions or post to Discord
      </div>
    </PerryPanel>
  )
}

// ============ Trigger Timeline Panel ============

function TriggerTimelinePanel({ onGameClick }) {
  const [timeline, setTimeline] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchTimeline = async () => {
    setLoading(true)
    try {
      const data = await fetchAPI('/timeline/today')
      setTimeline(data)
    } catch (err) {
      console.error('Failed to fetch timeline:', err)
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchTimeline()
    const interval = setInterval(fetchTimeline, 60000) // Refresh every minute
    return () => clearInterval(interval)
  }, [])

  const getTriggerIcon = (status) => {
    switch (status) {
      case 'correct':
        return <CheckCircle size={12} className="text-green-400" />
      case 'wrong':
        return <XCircle size={12} className="text-red-400" />
      case 'pending':
        return <Clock size={12} className="text-yellow-400" />
      default:
        return <AlertCircle size={12} className="text-slate-400" />
    }
  }

  if (loading) {
    return (
      <PerryPanel title="Today's Trigger Timeline" icon={Timer}>
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={20} className="animate-spin text-teal-400" />
        </div>
      </PerryPanel>
    )
  }

  if (!timeline) return null

  return (
    <PerryPanel title={`Today's Games - ${timeline.date}`} icon={Timer}>
      <div className="flex justify-between items-center mb-3">
        <div className="text-xs text-slate-400">
          {timeline.total_games} games • {timeline.triggers_fired} triggers fired • {timeline.triggers_pending} pending
        </div>
        <PerryButton onClick={fetchTimeline}>
          <RefreshCw size={12} />
        </PerryButton>
      </div>

      <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-64 overflow-y-auto">
        {timeline.games.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50 sticky top-0">
              <tr>
                <th className="text-left p-2 text-slate-400 font-medium">Game</th>
                <th className="text-left p-2 text-slate-400 font-medium">Time</th>
                <th className="text-center p-2 text-slate-400 font-medium">Pregame</th>
                <th className="text-center p-2 text-slate-400 font-medium">HT</th>
                <th className="text-center p-2 text-slate-400 font-medium">Q3</th>
                <th className="text-center p-2 text-slate-400 font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {timeline.games.map((game, i) => (
                <tr
                  key={game.nba_id || i}
                  onClick={() => game.game_id && onGameClick && onGameClick(game.game_id)}
                  className="border-t border-slate-700/50 hover:bg-slate-800/30 cursor-pointer"
                >
                  <td className="p-2 text-slate-300">
                    <div className="text-xs">{game.away_team} @ {game.home_team}</div>
                  </td>
                  <td className="p-2 text-slate-500 text-xs">
                    {formatGameTime(game.game_time)}
                  </td>
                  <td className="p-2 text-center">{getTriggerIcon(game.triggers.pregame.status)}</td>
                  <td className="p-2 text-center">{getTriggerIcon(game.triggers.halftime.status)}</td>
                  <td className="p-2 text-center">{getTriggerIcon(game.triggers.q3_5min.status)}</td>
                  <td className="p-2 text-center text-white text-xs">
                    {game.home_score !== null ? `${game.away_score} - ${game.home_score}` : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="p-4 text-center text-slate-500">No games scheduled for today</div>
        )}
      </div>

      {/* Legend */}
      <div className="flex gap-4 mt-2 text-xs text-slate-500">
        <div className="flex items-center gap-1"><CheckCircle size={10} className="text-green-400" /> Correct</div>
        <div className="flex items-center gap-1"><XCircle size={10} className="text-red-400" /> Wrong</div>
        <div className="flex items-center gap-1"><Clock size={10} className="text-yellow-400" /> Pending</div>
        <div className="flex items-center gap-1"><AlertCircle size={10} className="text-slate-400" /> Not triggered</div>
      </div>
    </PerryPanel>
  )
}

// ============ Model Confidence Display ============

function ConfidenceBadge({ tier, probability }) {
  const config = {
    'A+': { bg: 'bg-green-500/20', text: 'text-green-400', border: 'border-green-500/30', label: 'A+ (High)' },
    'A': { bg: 'bg-teal-500/20', text: 'text-teal-400', border: 'border-teal-500/30', label: 'A' },
    'B+': { bg: 'bg-yellow-500/20', text: 'text-yellow-400', border: 'border-yellow-500/30', label: 'B+' },
    'B': { bg: 'bg-slate-500/20', text: 'text-slate-400', border: 'border-slate-500/30', label: 'B' },
  }
  const c = config[tier] || config['B']

  return (
    <div className="flex items-center gap-2">
      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${c.bg} ${c.text} border ${c.border}`}>
        {tier || 'B'}
      </span>
      {probability && (
        <span className="text-xs text-slate-500">{(probability * 100).toFixed(0)}%</span>
      )}
    </div>
  )
}

// ============ Testing Panel ============

function TestingPanel({ onRefresh }) {
  const [systemStatus, setSystemStatus] = useState(null)
  const [discordTestResult, setDiscordTestResult] = useState(null)
  const [predictionTestResult, setPredictionTestResult] = useState(null)
  const [dbTestResult, setDbTestResult] = useState(null)
  const [oddsStatus, setOddsStatus] = useState(null)
  const [fakeTriggers, setFakeTriggers] = useState([])
  const [loading, setLoading] = useState({})
  const [newTriggerDelay, setNewTriggerDelay] = useState(30)
  const [postToDiscord, setPostToDiscord] = useState(true)

  const fetchStatus = async () => {
    setLoading(prev => ({ ...prev, status: true }))
    try {
      const data = await fetchAPI('/test/status')
      setSystemStatus(data)
    } catch (err) {
      setSystemStatus({ overall: 'error', components: {}, error: err.message })
    }
    setLoading(prev => ({ ...prev, status: false }))
  }

  const fetchOddsStatus = async () => {
    try {
      const data = await fetchAPI('/test/odds-status')
      setOddsStatus(data)
    } catch (err) {
      setOddsStatus({ configured: false, message: err.message })
    }
  }

  const fetchFakeTriggers = async () => {
    try {
      const data = await fetchAPI('/test/fake-triggers')
      setFakeTriggers(data.triggers || [])
    } catch (err) {
      console.error('Failed to fetch triggers:', err)
    }
  }

  useEffect(() => {
    fetchStatus()
    fetchOddsStatus()
    fetchFakeTriggers()
    const interval = setInterval(() => {
      fetchFakeTriggers()
    }, 5000)
    return () => clearInterval(interval)
  }, [])

  const testDiscord = async () => {
    setLoading(prev => ({ ...prev, discord: true }))
    setDiscordTestResult(null)
    try {
      const result = await fetchAPI('/test/discord', {
        method: 'POST',
        body: JSON.stringify({ message: '🧪 Test from PerryPicks Dashboard' }),
      })
      setDiscordTestResult(result)
    } catch (err) {
      setDiscordTestResult({ success: false, message: err.message })
    }
    setLoading(prev => ({ ...prev, discord: false }))
  }

  const testPrediction = async () => {
    setLoading(prev => ({ ...prev, prediction: true }))
    setPredictionTestResult(null)
    try {
      const result = await fetchAPI('/test/prediction', { method: 'POST' })
      setPredictionTestResult(result)
    } catch (err) {
      setPredictionTestResult({ success: false, message: err.message })
    }
    setLoading(prev => ({ ...prev, prediction: false }))
  }

  const testDatabase = async () => {
    setLoading(prev => ({ ...prev, database: true }))
    setDbTestResult(null)
    try {
      const result = await fetchAPI('/test/database', { method: 'POST' })
      setDbTestResult(result)
    } catch (err) {
      setDbTestResult({ success: false, message: err.message })
    }
    setLoading(prev => ({ ...prev, database: false }))
  }

  const queueFakeTrigger = async () => {
    setLoading(prev => ({ ...prev, trigger: true }))
    try {
      await fetchAPI('/test/fake-trigger', {
        method: 'POST',
        body: JSON.stringify({
          delay_seconds: newTriggerDelay,
          post_to_discord: postToDiscord,
        }),
      })
      fetchFakeTriggers()
    } catch (err) {
      alert('Failed to queue trigger: ' + err.message)
    }
    setLoading(prev => ({ ...prev, trigger: false }))
  }

  const clearTriggers = async () => {
    try {
      await fetchAPI('/test/fake-triggers', { method: 'DELETE' })
      fetchFakeTriggers()
    } catch (err) {
      console.error('Failed to clear triggers:', err)
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'healthy':
      case 'configured':
        return <CheckCircle size={16} className="text-green-400" />
      case 'error':
        return <XCircle size={16} className="text-red-400" />
      case 'warning':
      case 'degraded':
        return <AlertCircle size={16} className="text-yellow-400" />
      default:
        return <AlertCircle size={16} className="text-slate-400" />
    }
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'healthy':
      case 'configured':
        return 'text-green-400'
      case 'error':
        return 'text-red-400'
      case 'warning':
      case 'degraded':
        return 'text-yellow-400'
      default:
        return 'text-slate-400'
    }
  }

  return (
    <div className="space-y-4">
      {/* System Status Panel */}
      <PerryPanel title="System Status" icon={Activity}>
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2">
            {systemStatus?.overall === 'healthy' ? (
              <span className="text-green-400 font-medium">All Systems Operational</span>
            ) : (
              <span className="text-yellow-400 font-medium">System Issues Detected</span>
            )}
          </div>
          <PerryButton onClick={fetchStatus} disabled={loading.status}>
            <RefreshCw size={14} className={loading.status ? 'animate-spin' : ''} />
            Refresh
          </PerryButton>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {systemStatus?.components && Object.entries(systemStatus.components).map(([name, info]) => (
            <div key={name} className="bg-slate-900/50 rounded-lg p-3 border border-slate-700/50">
              <div className="flex items-center gap-2 mb-1">
                {getStatusIcon(info.status)}
                <span className="text-sm font-medium text-white capitalize">{name.replace('_', ' ')}</span>
              </div>
              <div className={`text-xs ${getStatusColor(info.status)}`}>{info.message}</div>
            </div>
          ))}
        </div>

        {systemStatus?.error && (
          <div className="mt-3 p-2 bg-red-500/20 rounded text-red-400 text-sm">
            {systemStatus.error}
          </div>
        )}
      </PerryPanel>

      {/* Discord Test */}
      <PerryPanel title="Discord Connection" icon={MessageSquare}>
        <div className="flex items-center gap-4 mb-4">
          <PerryButton onClick={testDiscord} disabled={loading.discord} primary>
            <Send size={14} />
            {loading.discord ? 'Sending...' : 'Send Test Message'}
          </PerryButton>
          {discordTestResult && (
            <span className={discordTestResult.success ? 'text-green-400' : 'text-red-400'}>
              {discordTestResult.message}
            </span>
          )}
        </div>
        <p className="text-xs text-slate-500">
          This will post a test message to your configured Discord channel.
        </p>
      </PerryPanel>

      {/* Fake Trigger Test */}
      <PerryPanel title="Trigger Testing" icon={Timer}>
        <div className="mb-4">
          <div className="flex items-end gap-4 mb-3">
            <div className="flex-1">
              <label className="block text-xs font-medium text-slate-400 mb-1">Delay (seconds)</label>
              <input
                type="number"
                value={newTriggerDelay}
                onChange={(e) => setNewTriggerDelay(parseInt(e.target.value) || 30)}
                className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-600 text-slate-100"
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPostToDiscord(!postToDiscord)}
                className={`w-10 h-5 rounded-full transition-colors ${postToDiscord ? 'bg-teal-500' : 'bg-slate-600'}`}
              >
                <div className={`w-4 h-4 rounded-full bg-white transition-transform ${postToDiscord ? 'translate-x-5' : 'translate-x-0.5'}`}></div>
              </button>
              <span className="text-sm text-slate-300">Post to Discord</span>
            </div>
            <PerryButton onClick={queueFakeTrigger} disabled={loading.trigger} accent>
              <Play size={14} />
              Queue Fake Trigger
            </PerryButton>
          </div>
          <p className="text-xs text-slate-500 mb-3">
            ⚠️ Fake triggers do NOT fetch odds (saves API credits). They will generate a test prediction and optionally post to Discord.
          </p>
        </div>

        {/* Trigger Queue */}
        <div>
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium text-slate-400">Trigger Queue ({fakeTriggers.length})</span>
            <button onClick={clearTriggers} className="text-xs text-slate-500 hover:text-slate-300">Clear completed</button>
          </div>
          <div className="bg-slate-900/50 rounded-lg border border-slate-700/50 max-h-32 overflow-y-auto">
            {fakeTriggers.length > 0 ? (
              <table className="w-full text-sm">
                <tbody>
                  {fakeTriggers.map((trigger) => (
                    <tr key={trigger.id} className="border-t border-slate-700/50 first:border-t-0">
                      <td className="p-2 text-slate-300 font-mono text-xs">{trigger.id}</td>
                      <td className="p-2 text-slate-400">{trigger.delay_seconds}s delay</td>
                      <td className="p-2">
                        <span className={`px-2 py-0.5 rounded text-xs ${trigger.status === 'completed' ? 'bg-green-500/20 text-green-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                          {trigger.status}
                        </span>
                      </td>
                      <td className="p-2 text-slate-500 text-xs">{trigger.post_to_discord ? 'Discord ✓' : 'No Discord'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4 text-center text-slate-500">No triggers queued</div>
            )}
          </div>
        </div>
      </PerryPanel>

      {/* Component Tests */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <PerryPanel title="Prediction Model" icon={Target}>
          <PerryButton onClick={testPrediction} disabled={loading.prediction} className="mb-3">
            <TestTube size={14} />
            {loading.prediction ? 'Testing...' : 'Test Prediction'}
          </PerryButton>
          {predictionTestResult && (
            <div className={`p-3 rounded-lg ${predictionTestResult.success ? 'bg-green-500/10 border border-green-500/30' : 'bg-red-500/10 border border-red-500/30'}`}>
              {predictionTestResult.success ? (
                <div className="text-sm">
                  <div className="text-slate-400 mb-1">Input: H1 {predictionTestResult.input.h1_home} - {predictionTestResult.input.h1_away}</div>
                  <div className="text-white">Total: <span className="font-bold">{predictionTestResult.prediction.pred_final_total?.toFixed(1)}</span></div>
                  <div className="text-white">Margin: <span className="font-bold">{predictionTestResult.prediction.pred_final_margin?.toFixed(1)}</span></div>
                  <div className="text-white">Win Prob: <span className="font-bold">{(predictionTestResult.prediction.home_win_prob * 100).toFixed(1)}%</span></div>
                </div>
              ) : (
                <div className="text-red-400">{predictionTestResult.message}</div>
              )}
            </div>
          )}
        </PerryPanel>

        <PerryPanel title="Database" icon={Database}>
          <PerryButton onClick={testDatabase} disabled={loading.database} className="mb-3">
            <TestTube size={14} />
            {loading.database ? 'Testing...' : 'Test Write/Delete'}
          </PerryButton>
          {dbTestResult && (
            <div className={`p-3 rounded-lg ${dbTestResult.success ? 'bg-green-500/10 border border-green-500/30' : 'bg-red-500/10 border border-red-500/30'}`}>
              <span className={dbTestResult.success ? 'text-green-400' : 'text-red-400'}>
                {dbTestResult.message}
              </span>
            </div>
          )}
          <div className="mt-3 pt-3 border-t border-slate-700">
            <div className="text-xs text-slate-500">
              Odds API: {oddsStatus?.configured ? (
                <span className="text-green-400">Configured ({oddsStatus.key_preview})</span>
              ) : (
                <span className="text-yellow-400">Not configured</span>
              )}
            </div>
          </div>
        </PerryPanel>
      </div>
    </div>
  )
}

// ============ Main App ============

function App() {
  const [performanceData, setPerformanceData] = useState(null)
  const [ghostStats, setGhostStats] = useState(null)
  const [ghostConfig, setGhostConfig] = useState(null)
  const [ghostBets, setGhostBets] = useState([])
  const [liveGames, setLiveGames] = useState([])
  const [predictions, setPredictions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [activeTab, setActiveTab] = useState('dashboard')
  const [selectedGameId, setSelectedGameId] = useState(null)
  const [performancePeriod, setPerformancePeriod] = useState('30d')

  const getPeriodDays = (period) => {
    switch (period) {
      case '7d': return 7
      case '30d': return 30
      case '90d': return 90
      case 'all': return 365
      default: return 30
    }
  }

  const loadAllData = async (isInitialLoad = false) => {
    if (isInitialLoad) setLoading(true)
    setError(null)
    try {
      const periodDays = getPeriodDays(performancePeriod)
      const [perf, stats, config, bets, live, preds] = await Promise.all([
        fetchAPI(`/predictions/performance?days=${periodDays}`).catch(() => null),
        fetchAPI('/ghost-bettor/stats?days=30').catch(() => null),
        fetchAPI('/ghost-bettor/config').catch(() => null),
        fetchAPI('/ghost-bettor/bets?limit=20').catch(() => []),
        fetchAPI('/live/scores').catch(() => ({ games: [] })),
        fetchAPI('/predictions?limit=20').catch(() => []),
      ])
      setPerformanceData(perf)
      setGhostStats(stats)
      setGhostConfig(config)
      setGhostBets(bets)
      setLiveGames(live?.games || [])
      setPredictions(preds)
      setLastRefresh(new Date().toLocaleTimeString())
    } catch (err) {
      console.error('Failed to load data:', err)
      setError(err.message || 'Failed to load dashboard data. Check if the backend is running.')
    }
    if (isInitialLoad) setLoading(false)
  }

  // Callback to update ghost config state directly (for immediate UI updates after save)
  const onGhostConfigSaved = async (newConfig) => {
    // Update config state immediately
    setGhostConfig(newConfig)
    // Also refresh stats to get updated bankroll
    const stats = await fetchAPI('/ghost-bettor/stats?days=30').catch(() => null)
    if (stats) setGhostStats(stats)
  }

  useEffect(() => {
    loadAllData(true)
    const interval = setInterval(() => loadAllData(false), 30000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <div className="max-w-7xl mx-auto p-4 space-y-4">
        {/* Header */}
        <div className="bg-gradient-to-r from-teal-600 to-teal-500 rounded-xl lg:rounded-2xl p-3 lg:p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 lg:w-10 lg:h-10 bg-white/20 rounded-lg lg:rounded-xl flex items-center justify-center">
              <span className="text-xl lg:text-2xl">🦆</span>
            </div>
            <div>
              <h1 className="text-lg lg:text-xl font-bold text-white">PerryPicks Dashboard</h1>
              <p className="text-teal-100 text-xs lg:text-sm flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${error ? 'bg-red-400' : 'bg-green-400'}`}></span>
                REPTAR Model • Auto-refresh: 30s
              </p>
            </div>
          </div>
          <div className="text-left sm:text-right text-xs lg:text-sm text-teal-100">
            {lastRefresh && <div>Last refresh: {lastRefresh}</div>}
            <div>{formatLocalDate(new Date())}</div>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="bg-red-500/20 border border-red-500/30 rounded-xl p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <AlertCircle className="text-red-400" size={20} />
              <div>
                <div className="text-red-400 font-medium">Connection Error</div>
                <div className="text-red-300/70 text-sm">{error}</div>
              </div>
            </div>
            <PerryButton onClick={() => loadAllData(true)}>
              <RefreshCw size={14} />
              Retry
            </PerryButton>
          </div>
        )}

        {/* Tab Navigation */}
        <div className="flex gap-2 overflow-x-auto pb-1">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`px-3 lg:px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
              activeTab === 'dashboard'
                ? 'bg-teal-500 text-white'
                : 'bg-slate-700/50 text-slate-400 hover:text-white hover:bg-slate-700'
            }`}
          >
            <BarChart3 size={16} className="inline-block mr-1 lg:mr-2" />
            Dashboard
          </button>
          <button
            onClick={() => setActiveTab('testing')}
            className={`px-3 lg:px-4 py-2 rounded-lg font-medium transition-colors whitespace-nowrap ${
              activeTab === 'testing'
                ? 'bg-orange-500 text-white'
                : 'bg-slate-700/50 text-slate-400 hover:text-white hover:bg-slate-700'
            }`}
          >
            <TestTube size={16} className="inline-block mr-1 lg:mr-2" />
            Testing
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === 'testing' ? (
          <TestingPanel onRefresh={loadAllData} />
        ) : (
          <>
            {loading && !performanceData ? (
              <div className="bg-slate-800/50 rounded-2xl p-8 flex items-center justify-center">
                <div className="flex items-center gap-3 text-slate-400">
                  <RefreshCw size={20} className="animate-spin" />
                  <span>Loading...</span>
                </div>
              </div>
            ) : (
              <>
                {/* Daily Summary - Full Width */}
                <DailySummaryPanel date={new Date().toISOString().split('T')[0]} />

                {/* Top Row */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <PerformancePanel
                    data={performanceData}
                    onRefresh={loadAllData}
                    period={performancePeriod}
                    onPeriodChange={(p) => {
                      setPerformancePeriod(p)
                      loadAllData(false)
                    }}
                  />
                  <GhostBettorPanel
                    stats={ghostStats}
                    config={ghostConfig}
                    bets={ghostBets}
                    onConfigSaved={onGhostConfigSaved}
                    onRefresh={loadAllData}
                  />
                </div>

                {/* Pending Triggers - Full Width */}
                <PendingTriggersPanel onRefresh={loadAllData} />

                {/* Trigger Timeline - Full Width */}
                <TriggerTimelinePanel onGameClick={(id) => setSelectedGameId(id)} />

                {/* Prediction History - Full Width */}
                <PredictionHistoryPanel onRefresh={loadAllData} />

                {/* Alert Panel - Full Width */}
                <AlertPanel />

                {/* Streak Tracker - Full Width */}
                <StreakTrackerPanel />

                {/* Team Performance - Full Width */}
                <TeamPerformancePanel />

                {/* Odds Comparison - Full Width */}
                <OddsComparisonPanel />

                {/* Automated Reporting - Full Width */}
                <AutomatedReportingPanel />

                {/* Live Bet Tracker - Full Width */}
                <LiveBetTrackerPanel />

                {/* Bottom Row - 3 columns */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  <TriggerConfigPanel />
                  <ManualPredictionPanel onPredictionMade={loadAllData} />
                  <OperationsPanel
                    games={liveGames}
                    predictions={predictions}
                    onRefresh={loadAllData}
                  />
                </div>
              </>
            )}
          </>
        )}

        {/* Game Detail Modal */}
        <GameDetailModal
          gameId={selectedGameId}
          onClose={() => setSelectedGameId(null)}
        />

        {/* Footer */}
        <div className="bg-slate-800/30 rounded-xl p-3 text-center">
          <p className="text-sm text-slate-500">
            PerryPicks REPTAR Model • Halftime MAE: <span className="text-slate-400">12.95 pts</span> • Margin MAE: <span className="text-slate-400">4.29 pts</span>
          </p>
        </div>
      </div>
    </div>
  )
}

export default function AppWithBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  )
}
