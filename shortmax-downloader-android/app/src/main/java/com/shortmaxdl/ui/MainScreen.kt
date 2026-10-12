package com.shortmaxdl.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    viewModel: MainViewModel,
    onNavigateToEpisodes: () -> Unit,
    onNavigateToSettings: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("ShortMax DL") },
                actions = {
                    IconButton(onClick = onNavigateToSettings) {
                        Icon(Icons.Default.Settings, contentDescription = "设置")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                )
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
        ) {
            // URL Input
            OutlinedTextField(
                value = uiState.urlInput,
                onValueChange = viewModel::updateUrlInput,
                label = { Text("粘贴 ShortMax 链接") },
                placeholder = { Text("https://www.shorttv.live/episode/...") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                isError = uiState.parseError != null,
                supportingText = uiState.parseError?.let { { Text(it) } },
            )

            Spacer(Modifier.height(12.dp))

            // Parse Button
            Button(
                onClick = {
                    if (uiState.isParsing) return@Button
                    viewModel.parseUrl()
                    // Navigate after short delay to let parse complete
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = !uiState.isParsing && uiState.urlInput.isNotBlank(),
            ) {
                if (uiState.isParsing) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary,
                    )
                    Spacer(Modifier.width(8.dp))
                }
                Icon(Icons.Default.Search, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(if (uiState.isParsing) "解析中..." else "解析剧集")
            }

            // Auto-navigate when episodes are loaded
            if (uiState.episodes.isNotEmpty()) {
                LaunchedEffect(uiState.episodes) {
                    onNavigateToEpisodes()
                }
            }

            Spacer(Modifier.height(24.dp))

            // Recent Downloads Section
            if (uiState.recentMovies.isNotEmpty()) {
                Text(
                    "最近下载",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Spacer(Modifier.height(8.dp))

                LazyColumn {
                    items(uiState.recentMovies) { movie ->
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                            ),
                            onClick = {
                                viewModel.updateUrlInput("https://www.shorttv.live/episode/short-${movie.movieId}-1")
                                viewModel.parseUrl()
                            }
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(12.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    "\uD83D\uDCFA",
                                    style = MaterialTheme.typography.headlineSmall,
                                )
                                Spacer(Modifier.width(12.dp))
                                Text(
                                    movie.movieTitle,
                                    style = MaterialTheme.typography.bodyLarge,
                                )
                            }
                        }
                    }
                }
            } else {
                // Empty state
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "粘贴 ShortMax 短剧链接开始下载\n\n支持 shorttv.live / shortmax.com",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
    }
}


