import { useState } from 'react'
import { Toaster } from 'sonner'
import { Sidebar } from '@/components/layout/Sidebar'
import { Workbench } from '@/workbench/Workbench'
import { EnvironmentCheck, isEnvChecked } from '@/components/env/EnvironmentCheck'
import { LicenseDisclaimer, isLicenseAccepted } from '@/components/license/LicenseDisclaimer'

function App() {
  // Initialize by checking localStorage if license has been accepted
  const [licenseAccepted, setLicenseAccepted] = useState(() => isLicenseAccepted())
  // Initialize by checking localStorage if env check has passed
  const [envChecked, setEnvChecked] = useState(() => isEnvChecked())
  // State for showing disclaimer manually
  const [showDisclaimer, setShowDisclaimer] = useState(false)
  const [connection, setConnection] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')

  const handleEnvCheckComplete = () => {
    setEnvChecked(true)
  }

  const handleLicenseAccept = () => {
    setLicenseAccepted(true)
    setShowDisclaimer(false)
  }

  const handleShowDisclaimer = () => {
    setShowDisclaimer(true)
  }

  return (
    <div className="flex flex-col h-dvh overflow-hidden relative">
      {/* License Disclaimer Modal - Shows first or when triggered */}
      {(!licenseAccepted || showDisclaimer) && (
        <LicenseDisclaimer onAccept={handleLicenseAccept} />
      )}

      {/* Environment Check Modal - Shows after license accepted */}
      {licenseAccepted && !showDisclaimer && !envChecked && (
        <EnvironmentCheck onCheckComplete={handleEnvCheckComplete} />
      )}

      {/* Header Bar */}
      <Sidebar onShowDisclaimer={handleShowDisclaimer} connection={connection} />

      {/* Main Area */}
      <Workbench onConnectionChange={setConnection} />

      {/* Author Footer */}


      {/* Toast notifications - Theme-aware style */}
      <Toaster
        position="top-right"
        toastOptions={{
          className: 'wb-toast',
          style: {
            fontFamily: 'Segoe UI, Microsoft YaHei UI, sans-serif',
          },
        }}
      />
    </div>
  )
}

export default App
