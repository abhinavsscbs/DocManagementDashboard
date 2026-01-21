import React, { createContext, useState, useContext } from 'react'

const AppContext = createContext()

export const useApp = () => {
  const context = useContext(AppContext)
  if (!context) {
    throw new Error('useApp must be used within AppProvider')
  }
  return context
}

export const AppProvider = ({ children }) => {
  const [selectedPipeline, setSelectedPipeline] = useState('ey')
  const [processingStatus, setProcessingStatus] = useState({
    isProcessing: false,
    currentStep: '',
    progress: 0,
  })
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)

  const clearError = () => setError(null)

  const clearResults = () => setResults(null)

  return (
    <AppContext.Provider
      value={{
        selectedPipeline,
        setSelectedPipeline,
        processingStatus,
        setProcessingStatus,
        results,
        setResults,
        error,
        setError,
        clearError,
        clearResults,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}
