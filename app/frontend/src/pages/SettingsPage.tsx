import { useEffect, useState } from 'react'
import {
  getSettings, getModels, getSttModels,
  AppSettings, StageSettings, SttModelInfo,
} from '../api'
import { GeneralPanel } from '../components/settings/GeneralPanel'
import { BoxedLayoutToggle } from '../components/settings/BoxedLayoutToggle'
import { ForceMapReduceToggle } from '../components/settings/ForceMapReduceToggle'
import { ModelOnlyPanel } from '../components/settings/ModelOnlyPanel'
import { StagePanel } from '../components/settings/StagePanel'
import { SttPanel } from '../components/settings/SttPanel'
import { FileStoragePanel } from '../components/settings/FileStoragePanel'
import { ConnectionsPanel } from '../components/settings/ConnectionsPanel'

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type TabId = 'general' | 'cleanup' | 'summarization' | 'chat' | 'stt' | 'storage' | 'connections'
type SummSubTab = 'single_pass' | 'map_reduce'
type MapReduceStep = 'extract' | 'combine'

const TABS: { id: TabId; label: string }[] = [
  { id: 'general',       label: 'General' },
  { id: 'cleanup',       label: 'AI Cleanup' },
  { id: 'summarization', label: 'Summarization' },
  { id: 'chat',          label: 'Chat' },
  { id: 'stt',           label: 'Speech-to-Text' },
  { id: 'storage',       label: 'File Storage' },
  { id: 'connections',   label: 'Connections' },
]

export default function SettingsPage() {
  const [activeTab, setActiveTab]   = useState<TabId>('general')
  const [summSubTab, setSummSubTab] = useState<SummSubTab>('single_pass')
  const [mapReduceStep, setMapReduceStep] = useState<MapReduceStep>('extract')

  const [appSettings, setAppSettings]   = useState<AppSettings | null>(null)
  const [cleanup, setCleanup]           = useState<StageSettings | null>(null)
  const [summarization, setSummarization] = useState<StageSettings | null>(null)
  const [summExtract, setSummExtract]   = useState<StageSettings | null>(null)
  const [summCombine, setSummCombine]   = useState<StageSettings | null>(null)
  const [chat, setChat]                 = useState<StageSettings | null>(null)
  const [models, setModels]             = useState<string[]>([])
  const [modelsOnline, setModelsOnline] = useState(true)
  const [sttModels, setSttModels]       = useState<SttModelInfo[]>([])
  const [error, setError]               = useState('')

  useEffect(() => {
    getSettings()
      .then(s => {
        setAppSettings(s.app)
        setCleanup(s.cleanup)
        setSummarization(s.summarization)
        setSummExtract(s.summarization_extract)
        setSummCombine(s.summarization_combine)
        setChat(s.chat)
      })
      .catch(() => setError('Could not load settings'))

    getModels()
      .then(list => { setModels(list); setModelsOnline(true) })
      .catch(() => setModelsOnline(false))

    getSttModels().then(setSttModels).catch(() => {})
  }, [])

  function reloadSttModels() {
    getSttModels().then(setSttModels).catch(() => {})
  }

  if (error) return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="bg-error-container border border-error/30 rounded-xl p-6 text-on-error-container">{error}</div>
    </div>
  )

  if (!appSettings || !cleanup || !summarization || !summExtract || !summCombine || !chat) return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto">
      <div className="py-16 text-center text-secondary text-body-md">Loading…</div>
    </div>
  )

  return (
    <div className="p-6 md:p-8 max-w-[1200px] mx-auto space-y-6">

      {/* Page header */}
      <div>
        <h2 className="text-headline-xl font-bold text-on-surface">Settings</h2>
        <p className="text-body-md text-on-surface-variant mt-1">Configure the application. All settings are stored in the database.</p>
      </div>

      {/* Main card */}
      <div className="bg-surface-container-lowest border border-outline-variant rounded-xl shadow-sm overflow-hidden">

        {/* Tab bar */}
        <div className="flex border-b border-outline-variant px-6">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-4 px-6 text-label-md border-b-2 transition-all ${
                activeTab === tab.id
                  ? 'border-primary text-primary font-bold'
                  : 'border-transparent text-on-surface-variant hover:text-on-surface'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="p-6">

          {/* General */}
          {activeTab === 'general' && (
            <div className="space-y-6">
              <GeneralPanel initial={appSettings} onSaved={setAppSettings} />
              <div className="border-t border-outline-variant pt-5 space-y-3">
                <p className="text-label-sm text-on-surface-variant uppercase tracking-wider font-bold">Display</p>
                <BoxedLayoutToggle />
              </div>
            </div>
          )}

          {/* AI Cleanup */}
          {activeTab === 'cleanup' && (
            <div className="space-y-5">
              <div className="space-y-1.5">
                <label className="text-label-md text-on-surface flex items-center gap-1">
                  Model <span className="text-error">*</span>
                </label>
                <ModelOnlyPanel
                  stage="cleanup"
                  initial={cleanup}
                  models={models}
                  modelsOnline={modelsOnline}
                  onSaved={setCleanup}
                />
              </div>
              <StagePanel
                stage="cleanup"
                initial={cleanup}
                models={models}
                modelsOnline={modelsOnline}
                hideModel
              />
            </div>
          )}

          {/* Summarization */}
          {activeTab === 'summarization' && (
            <div className="space-y-5">

              {/* Force Map-Reduce */}
              <ForceMapReduceToggle
                value={appSettings.force_map_reduce === 'true'}
                onSaved={setAppSettings}
              />

              {/* Shared model selector */}
              <div className="space-y-1.5">
                <label className="text-label-md text-on-surface flex items-center gap-1">
                  Model <span className="text-error">*</span>
                </label>
                <ModelOnlyPanel
                  stage="summarization"
                  initial={summarization}
                  models={models}
                  modelsOnline={modelsOnline}
                  onSaved={setSummarization}
                />
              </div>

              {/* Sub-tabs: Single Pass / Map-Reduce */}
              <div className="border border-outline-variant rounded-lg overflow-hidden">
                <div className="bg-surface-container flex border-b border-outline-variant">
                  {([
                    { id: 'single_pass' as const, label: 'Single Pass' },
                    { id: 'map_reduce'  as const, label: 'Map-Reduce' },
                  ]).map(t => (
                    <button
                      key={t.id}
                      onClick={() => setSummSubTab(t.id)}
                      className={`px-6 py-2.5 text-label-md transition-colors ${
                        summSubTab === t.id
                          ? 'bg-surface-container-lowest text-primary border-b-2 border-primary font-bold'
                          : 'text-on-surface-variant hover:bg-surface-container-high'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>

                <div className="p-6">
                  {summSubTab === 'single_pass' && (
                    <StagePanel
                      stage="summarization"
                      initial={summarization}
                      models={models}
                      modelsOnline={modelsOnline}
                      hideModel
                    />
                  )}

                  {summSubTab === 'map_reduce' && (
                    <div className="space-y-5">
                      {/* Step tabs */}
                      <div className="flex gap-1 border-b border-outline-variant pb-0 -mx-6 px-6">
                        {([
                          { id: 'extract' as const, label: 'Step 1 — Extract (per chunk)' },
                          { id: 'combine' as const, label: 'Step 2 — Combine (all chunks)' },
                        ]).map(s => (
                          <button
                            key={s.id}
                            onClick={() => setMapReduceStep(s.id)}
                            className={`px-4 py-2 text-label-md border-b-2 transition-all -mb-px ${
                              mapReduceStep === s.id
                                ? 'border-primary text-primary font-bold'
                                : 'border-transparent text-on-surface-variant hover:text-on-surface'
                            }`}
                          >
                            {s.label}
                          </button>
                        ))}
                      </div>

                      {mapReduceStep === 'extract' && (
                        <StagePanel
                          stage="summarization_extract"
                          initial={summExtract}
                          models={models}
                          modelsOnline={modelsOnline}
                          hideModel
                        />
                      )}
                      {mapReduceStep === 'combine' && (
                        <StagePanel
                          stage="summarization_combine"
                          initial={summCombine}
                          models={models}
                          modelsOnline={modelsOnline}
                          hideModel
                        />
                      )}
                    </div>
                  )}
                </div>
              </div>

            </div>
          )}

          {/* Chat */}
          {activeTab === 'chat' && (
            <div className="space-y-5">
              <p className="text-body-sm text-on-surface-variant">
                Model used for chat conversations on the Result page. If not set, falls back to the Summarization model.
              </p>
              <div className="space-y-1.5">
                <label className="text-label-md text-on-surface">Model</label>
                <ModelOnlyPanel
                  stage="chat"
                  initial={chat}
                  models={models}
                  modelsOnline={modelsOnline}
                  onSaved={setChat}
                />
              </div>
            </div>
          )}

          {/* Speech-to-Text */}
          {activeTab === 'stt' && (
            <SttPanel
              initial={appSettings}
              sttModels={sttModels}
              onSaved={setAppSettings}
              onReloadModels={reloadSttModels}
            />
          )}

          {/* File Storage */}
          {activeTab === 'storage' && (
            <FileStoragePanel initial={appSettings} />
          )}

          {/* Connections */}
          {activeTab === 'connections' && (
            <ConnectionsPanel />
          )}

        </div>
      </div>
    </div>
  )
}

