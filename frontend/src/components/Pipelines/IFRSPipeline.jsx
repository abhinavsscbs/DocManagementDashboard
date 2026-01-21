import React, { useState } from 'react'
import {
  Paper,
  Typography,
  Button,
  Box,
  Alert,
  CircularProgress,
  LinearProgress,
  Grid,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Divider,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import FolderIcon from '@mui/icons-material/Folder'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import FileUploader from '../FileUpload/FileUploader'

const IFRSPipeline = () => {
  // Mode state: 'upload' or 'folder'
  const [mode, setMode] = useState('upload')

  // Upload mode state
  const [filesA, setFilesA] = useState([])
  const [filesB, setFilesB] = useState([])
  const [filesC, setFilesC] = useState([])

  // Folder mode state
  const [folderPathA, setFolderPathA] = useState('')
  const [folderPathB, setFolderPathB] = useState('')
  const [folderPathC, setFolderPathC] = useState('')
  const [zipFileA, setZipFileA] = useState(null)
  const [zipFileB, setZipFileB] = useState(null)
  const [zipFileC, setZipFileC] = useState(null)

  // Processing state
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState(null)
  const [results, setResults] = useState(null)
  const [processingStage, setProcessingStage] = useState('')

  const handleModeChange = (event, newMode) => {
    if (newMode !== null) {
      setMode(newMode)
      setMessage(null)
      setResults(null)
    }
  }

  const handleFilesASelect = (selectedFiles) => {
    setFilesA(selectedFiles)
    setMessage(null)
  }

  const handleFilesBSelect = (selectedFiles) => {
    setFilesB(selectedFiles)
    setMessage(null)
  }

  const handleFilesCSelect = (selectedFiles) => {
    setFilesC(selectedFiles)
    setMessage(null)
  }

  const handleZipASelect = (selectedFile) => {
    setZipFileA(selectedFile)
    setMessage(null)
  }

  const handleZipBSelect = (selectedFile) => {
    setZipFileB(selectedFile)
    setMessage(null)
  }

  const handleZipCSelect = (selectedFile) => {
    setZipFileC(selectedFile)
    setMessage(null)
  }

  const handleProcessUpload = async () => {
    // Validate that all three parts have files
    if (filesA.length === 0 || filesB.length === 0 || filesC.length === 0) {
      setMessage({
        type: 'error',
        text: 'Please provide files for all three parts: IFRS A, IFRS B, and IFRS C.'
      })
      return
    }

    setLoading(true)
    setMessage(null)
    setResults(null)
    setProcessingStage('Uploading files...')

    try {
      const formData = new FormData()
      formData.append('mode', 'upload')

      // Append all IFRS A files
      filesA.forEach(file => {
        formData.append('ifrs_a_files', file)
      })

      // Append all IFRS B files
      filesB.forEach(file => {
        formData.append('ifrs_b_files', file)
      })

      // Append all IFRS C files
      filesC.forEach(file => {
        formData.append('ifrs_c_files', file)
      })

      setTimeout(() => setProcessingStage('Processing IFRS Part A...'), 1000)
      setTimeout(() => setProcessingStage('Processing IFRS Part B...'), 3000)
      setTimeout(() => setProcessingStage('Processing IFRS Part C...'), 5000)
      setTimeout(() => setProcessingStage('Building FAISS indexes...'), 7000)

      const response = await fetch('/api/process/ifrs', {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (response.ok) {
        setMessage({
          type: 'success',
          text: `All three IFRS databases built successfully! Time: ${data.total_time_minutes.toFixed(2)} minutes`
        })
        setResults(data)
      } else {
        setMessage({
          type: 'error',
          text: data.message || data.error || 'Processing failed'
        })
      }
    } catch (error) {
      setMessage({ type: 'error', text: error.message })
    } finally {
      setLoading(false)
      setProcessingStage('')
    }
  }

  const handleProcessFolder = async () => {
    // Validate that each part has either a folder path or ZIP file
    if (!(folderPathA || zipFileA) || !(folderPathB || zipFileB) || !(folderPathC || zipFileC)) {
      setMessage({
        type: 'error',
        text: 'Please provide a folder/ZIP path or upload a ZIP for each of IFRS A, IFRS B, and IFRS C.'
      })
      return
    }

    setLoading(true)
    setMessage(null)
    setResults(null)
    setProcessingStage('Preparing folders/ZIP files...')

    try {
      const formData = new FormData()

      // Detect if any ZIP files are uploaded
      const hasZipFiles = zipFileA || zipFileB || zipFileC

      if (hasZipFiles) {
        // Use upload mode when ZIP files are present
        formData.append('mode', 'upload')

        // For each part, add ZIP file if uploaded, otherwise we'll need to handle folder paths differently
        // Note: Upload mode expects file arrays, so we create single-item arrays for ZIP files

        // IFRS A: Add ZIP file or skip (folder paths not supported in upload mode)
        if (zipFileA) {
          formData.append('ifrs_a_files', zipFileA)
        } else if (folderPathA) {
          // Can't mix folder paths with upload mode - need to inform user
          setMessage({
            type: 'error',
            text: 'Cannot mix folder paths and ZIP uploads. Please use either all folder paths or all ZIP files.'
          })
          setLoading(false)
          return
        }

        // IFRS B: Add ZIP file or skip
        if (zipFileB) {
          formData.append('ifrs_b_files', zipFileB)
        } else if (folderPathB) {
          setMessage({
            type: 'error',
            text: 'Cannot mix folder paths and ZIP uploads. Please use either all folder paths or all ZIP files.'
          })
          setLoading(false)
          return
        }

        // IFRS C: Add ZIP file or skip
        if (zipFileC) {
          formData.append('ifrs_c_files', zipFileC)
        } else if (folderPathC) {
          setMessage({
            type: 'error',
            text: 'Cannot mix folder paths and ZIP uploads. Please use either all folder paths or all ZIP files.'
          })
          setLoading(false)
          return
        }
      } else {
        // Use folder mode when only folder paths are provided
        formData.append('mode', 'folder')

        // Add folder paths
        if (folderPathA) formData.append('ifrs_a_path', folderPathA)
        if (folderPathB) formData.append('ifrs_b_path', folderPathB)
        if (folderPathC) formData.append('ifrs_c_path', folderPathC)
      }

      setTimeout(() => setProcessingStage('Processing IFRS Part A...'), 1000)
      setTimeout(() => setProcessingStage('Processing IFRS Part B...'), 3000)
      setTimeout(() => setProcessingStage('Processing IFRS Part C...'), 5000)
      setTimeout(() => setProcessingStage('Building FAISS indexes...'), 7000)

      const response = await fetch('/api/process/ifrs', {
        method: 'POST',
        body: formData,
      })

      const data = await response.json()

      if (response.ok) {
        setMessage({
          type: 'success',
          text: `All three IFRS databases built successfully from ${hasZipFiles ? 'ZIP files' : 'folders'}! Time: ${data.total_time_minutes.toFixed(2)} minutes`
        })
        setResults(data)
      } else {
        setMessage({
          type: 'error',
          text: data.message || data.error || 'Processing failed'
        })
      }
    } catch (error) {
      setMessage({ type: 'error', text: error.message })
    } finally {
      setLoading(false)
      setProcessingStage('')
    }
  }

  const downloadCSV = async (downloadToken, partName) => {
    try {
      const response = await fetch(`/api/download/csv/${downloadToken}`)
      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `ifrs_${partName.toLowerCase()}_chunks_preview.csv`
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      }
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        IFRS Pipeline (A + B + C)
      </Typography>
      <Typography variant="body2" color="text.secondary" paragraph>
        Process IFRS A, IFRS B, and IFRS C as separate databases. You can either upload multiple files per part (PDF/JSON) or enter local folder paths (or ZIP files) to crawl.
      </Typography>

      {/* Mode Selector */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="body2" sx={{ mb: 1, fontWeight: 500 }}>
          Input mode for IFRS parts:
        </Typography>
        <ToggleButtonGroup
          value={mode}
          exclusive
          onChange={handleModeChange}
          aria-label="input mode"
          size="small"
        >
          <ToggleButton value="upload" aria-label="upload files">
            <CloudUploadIcon sx={{ mr: 1 }} fontSize="small" />
            Upload files
          </ToggleButton>
          <ToggleButton value="folder" aria-label="use folders">
            <FolderIcon sx={{ mr: 1 }} fontSize="small" />
            Use local folders / ZIP paths
          </ToggleButton>
        </ToggleButtonGroup>
      </Box>

      {/* Upload Mode */}
      {mode === 'upload' && (
        <>
          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid item xs={12} md={4}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                IFRS A files (PDF/JSON)
              </Typography>
              <FileUploader
                accept=".pdf,.json"
                onFileSelect={handleFilesASelect}
                maxFiles={10}
                multiple
              />
              {filesA.length > 0 && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    {filesA.length} file(s) selected
                  </Typography>
                </Box>
              )}
            </Grid>
            <Grid item xs={12} md={4}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                IFRS B files (PDF/JSON)
              </Typography>
              <FileUploader
                accept=".pdf,.json"
                onFileSelect={handleFilesBSelect}
                maxFiles={10}
                multiple
              />
              {filesB.length > 0 && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    {filesB.length} file(s) selected
                  </Typography>
                </Box>
              )}
            </Grid>
            <Grid item xs={12} md={4}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                IFRS C files (PDF/JSON)
              </Typography>
              <FileUploader
                accept=".pdf,.json"
                onFileSelect={handleFilesCSelect}
                maxFiles={10}
                multiple
              />
              {filesC.length > 0 && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    {filesC.length} file(s) selected
                  </Typography>
                </Box>
              )}
            </Grid>
          </Grid>

          <Button
            variant="contained"
            startIcon={loading ? <CircularProgress size={20} /> : <CloudUploadIcon />}
            onClick={handleProcessUpload}
            disabled={loading || filesA.length === 0 || filesB.length === 0 || filesC.length === 0}
            size="large"
            fullWidth
          >
            {loading ? 'Building IFRS A/B/C...' : '▶️ Build IFRS A/B/C'}
          </Button>
        </>
      )}

      {/* Folder Mode */}
      {mode === 'folder' && (
        <>
          <Alert severity="info" sx={{ mb: 2 }}>
            <strong>Option 1:</strong> Enter local folder paths (or .zip file paths) that contain PDFs/JSONs — we'll scan recursively.
            <br />
            <strong>Option 2:</strong> Upload a ZIP file for each part using the file uploaders below.
            <br />
            <em>Note: Please use either all folder paths OR all ZIP uploads — mixing is not supported.</em>
          </Alert>

          <Grid container spacing={2} sx={{ mb: 3 }}>
            <Grid item xs={12} md={4}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                IFRS A
              </Typography>
              <TextField
                fullWidth
                size="small"
                label="Folder/ZIP path for IFRS A"
                value={folderPathA}
                onChange={(e) => setFolderPathA(e.target.value)}
                sx={{ mb: 2 }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                …or upload IFRS A ZIP:
              </Typography>
              <FileUploader
                accept=".zip"
                onFileSelect={handleZipASelect}
                maxFiles={1}
              />
              {zipFileA && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  {zipFileA.name}
                </Typography>
              )}
            </Grid>
            <Grid item xs={12} md={4}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                IFRS B
              </Typography>
              <TextField
                fullWidth
                size="small"
                label="Folder/ZIP path for IFRS B"
                value={folderPathB}
                onChange={(e) => setFolderPathB(e.target.value)}
                sx={{ mb: 2 }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                …or upload IFRS B ZIP:
              </Typography>
              <FileUploader
                accept=".zip"
                onFileSelect={handleZipBSelect}
                maxFiles={1}
              />
              {zipFileB && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  {zipFileB.name}
                </Typography>
              )}
            </Grid>
            <Grid item xs={12} md={4}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                IFRS C
              </Typography>
              <TextField
                fullWidth
                size="small"
                label="Folder/ZIP path for IFRS C"
                value={folderPathC}
                onChange={(e) => setFolderPathC(e.target.value)}
                sx={{ mb: 2 }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                …or upload IFRS C ZIP:
              </Typography>
              <FileUploader
                accept=".zip"
                onFileSelect={handleZipCSelect}
                maxFiles={1}
              />
              {zipFileC && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                  {zipFileC.name}
                </Typography>
              )}
            </Grid>
          </Grid>

          <Button
            variant="contained"
            startIcon={loading ? <CircularProgress size={20} /> : <FolderIcon />}
            onClick={handleProcessFolder}
            disabled={
              loading ||
              (!(folderPathA || zipFileA) || !(folderPathB || zipFileB) || !(folderPathC || zipFileC))
            }
            size="large"
            fullWidth
          >
            {loading ? 'Building IFRS A/B/C...' : '▶️ Build IFRS A/B/C (folders or ZIPs)'}
          </Button>
        </>
      )}

      {/* Progress Indicator */}
      {loading && (
        <Box sx={{ mt: 3 }}>
          <LinearProgress />
          <Box sx={{ display: 'flex', alignItems: 'center', mt: 1 }}>
            <CircularProgress size={16} sx={{ mr: 1 }} />
            <Typography variant="body2" color="text.secondary">
              {processingStage}
            </Typography>
          </Box>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
            This may take 5-15 minutes depending on file size and number of documents.
          </Typography>
        </Box>
      )}

      {/* Messages */}
      {message && (
        <Alert severity={message.type} sx={{ mt: 2 }}>
          {message.text}
        </Alert>
      )}

      {/* Results Display */}
      {results && (
        <Box sx={{ mt: 3 }}>
          <Divider sx={{ my: 2 }} />

          <Typography variant="h6" gutterBottom>
            Results
          </Typography>

          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} md={4}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  IFRS A
                </Typography>
                <Typography variant="h4">
                  {results.ifrs_a?.chunks_count || 0}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  chunks extracted
                </Typography>
                {results.ifrs_a?.download_token && (
                  <Button
                    size="small"
                    sx={{ mt: 1 }}
                    onClick={() => downloadCSV(results.ifrs_a.download_token, 'A')}
                  >
                    ⬇️ Download CSV
                  </Button>
                )}
              </Paper>
            </Grid>
            <Grid item xs={12} md={4}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  IFRS B
                </Typography>
                <Typography variant="h4">
                  {results.ifrs_b?.chunks_count || 0}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  chunks extracted
                </Typography>
                {results.ifrs_b?.download_token && (
                  <Button
                    size="small"
                    sx={{ mt: 1 }}
                    onClick={() => downloadCSV(results.ifrs_b.download_token, 'B')}
                  >
                    ⬇️ Download CSV
                  </Button>
                )}
              </Paper>
            </Grid>
            <Grid item xs={12} md={4}>
              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" color="text.secondary">
                  IFRS C
                </Typography>
                <Typography variant="h4">
                  {results.ifrs_c?.chunks_count || 0}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  chunks extracted
                </Typography>
                {results.ifrs_c?.download_token && (
                  <Button
                    size="small"
                    sx={{ mt: 1 }}
                    onClick={() => downloadCSV(results.ifrs_c.download_token, 'C')}
                  >
                    ⬇️ Download CSV
                  </Button>
                )}
              </Paper>
            </Grid>
          </Grid>

          <Chip
            label={`Total processing time: ${results.total_time_minutes?.toFixed(2) || 0} minutes`}
            color="primary"
            variant="outlined"
            sx={{ mb: 2 }}
          />

          {/* Preview Accordions for each part */}
          {(results.ifrs_a?.preview_data || results.ifrs_b?.preview_data || results.ifrs_c?.preview_data) && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="h6" gutterBottom>
                Preview Data (top 1,000 rows per part)
              </Typography>

              {/* IFRS A Preview */}
              {results.ifrs_a?.preview_data && results.ifrs_a.preview_data.length > 0 && (
                <Accordion defaultExpanded>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography fontWeight={600}>IFRS A Preview ({Math.min(1000, results.ifrs_a.preview_data.length)} rows)</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <TableContainer component={Paper} sx={{ maxHeight: 600 }}>
                      <Table stickyHeader size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Header</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Page</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Chapter</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Paragraph</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Preprocessed</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {results.ifrs_a.preview_data.map((row, idx) => (
                            <TableRow
                              key={idx}
                              sx={{
                                '&:nth-of-type(odd)': { bgcolor: 'grey.50' },
                                '&:hover': { bgcolor: 'action.hover' }
                              }}
                            >
                              <TableCell sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.header}
                              </TableCell>
                              <TableCell>{row.page}</TableCell>
                              <TableCell sx={{ maxWidth: 150 }}>{row.chapter_name}</TableCell>
                              <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                                {row.para}
                              </TableCell>
                              <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                                {row.preprocessed}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </AccordionDetails>
                </Accordion>
              )}

              {/* IFRS B Preview */}
              {results.ifrs_b?.preview_data && results.ifrs_b.preview_data.length > 0 && (
                <Accordion sx={{ mt: 1 }}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography fontWeight={600}>IFRS B Preview ({Math.min(1000, results.ifrs_b.preview_data.length)} rows)</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <TableContainer component={Paper} sx={{ maxHeight: 600 }}>
                      <Table stickyHeader size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Header</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Page</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Chapter</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Paragraph</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Preprocessed</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {results.ifrs_b.preview_data.map((row, idx) => (
                            <TableRow
                              key={idx}
                              sx={{
                                '&:nth-of-type(odd)': { bgcolor: 'grey.50' },
                                '&:hover': { bgcolor: 'action.hover' }
                              }}
                            >
                              <TableCell sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.header}
                              </TableCell>
                              <TableCell>{row.page}</TableCell>
                              <TableCell sx={{ maxWidth: 150 }}>{row.chapter_name}</TableCell>
                              <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                                {row.para}
                              </TableCell>
                              <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                                {row.preprocessed}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </AccordionDetails>
                </Accordion>
              )}

              {/* IFRS C Preview */}
              {results.ifrs_c?.preview_data && results.ifrs_c.preview_data.length > 0 && (
                <Accordion sx={{ mt: 1 }}>
                  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                    <Typography fontWeight={600}>IFRS C Preview ({Math.min(1000, results.ifrs_c.preview_data.length)} rows)</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <TableContainer component={Paper} sx={{ maxHeight: 600 }}>
                      <Table stickyHeader size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Header</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Page</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Chapter</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Paragraph</TableCell>
                            <TableCell sx={{ fontWeight: 600, bgcolor: 'grey.100' }}>Preprocessed</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {results.ifrs_c.preview_data.map((row, idx) => (
                            <TableRow
                              key={idx}
                              sx={{
                                '&:nth-of-type(odd)': { bgcolor: 'grey.50' },
                                '&:hover': { bgcolor: 'action.hover' }
                              }}
                            >
                              <TableCell sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {row.header}
                              </TableCell>
                              <TableCell>{row.page}</TableCell>
                              <TableCell sx={{ maxWidth: 150 }}>{row.chapter_name}</TableCell>
                              <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                                {row.para}
                              </TableCell>
                              <TableCell sx={{ maxWidth: 300, whiteSpace: 'pre-wrap' }}>
                                {row.preprocessed}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </AccordionDetails>
                </Accordion>
              )}
            </Box>
          )}
        </Box>
      )}
    </Paper>
  )
}

export default IFRSPipeline
