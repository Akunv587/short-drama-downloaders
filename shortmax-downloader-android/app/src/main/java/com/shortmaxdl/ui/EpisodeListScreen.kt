package com.shortmaxdl.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.shortmaxdl.domain.model.VideoQuality

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EpisodeListScreen(
    viewModel: MainViewModel,
    onBack: () -> Unit,
    onNavigateToDownloads: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsState()
    var showQualityMenu by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "${uiState.movieTitle} (${uiState.episodes.size}集)",
                        maxLines = 1,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                )
            )
        },
        bottomBar = {
            Surface(
                color = MaterialTheme.colorScheme.surface,
                shadowElevation = 8.dp,
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "已选 ${uiState.selectedEpisodes.size} / ${uiState.episodes.size} 集",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f),
                    )
                    Button(
                        onClick = {
                            viewModel.startDownload()
                            onNavigateToDownloads()
                        },
                        enabled = uiState.selectedEpisodes.isNotEmpty(),
                    ) {
                        Icon(Icons.Default.Download, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("下载所选 (${uiState.selectedEpisodes.size}集)")
                    }
                }
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            // Select all + quality selector row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // "全选" checkbox
                val allFreeSelected = uiState.episodes
                    .filter { !it.isVip }
                    .all { it.episodeNumber in uiState.selectedEpisodes }
                val hasFreeEpisodes = uiState.episodes.any { !it.isVip }
                TextButton(
                    onClick = {
                        if (allFreeSelected) {
                            // Deselect all
                            uiState.episodes.forEach { viewModel.toggleEpisodeSelection(it.episodeNumber) }
                        } else {
                            viewModel.selectAllFreeEpisodes()
                        }
                    },
                    enabled = hasFreeEpisodes,
                ) {
                    Checkbox(
                        checked = allFreeSelected && uiState.selectedEpisodes.isNotEmpty(),
                        onCheckedChange = null,
                        modifier = Modifier.size(24.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                    Text("全选")
                }

                Spacer(Modifier.weight(1f))

                // Quality selector
                Text("画质: ", style = MaterialTheme.typography.bodyMedium)
                Box {
                    TextButton(onClick = { showQualityMenu = true }) {
                        Text(uiState.videoQuality.label)
                    }
                    DropdownMenu(
                        expanded = showQualityMenu,
                        onDismissRequest = { showQualityMenu = false },
                    ) {
                        VideoQuality.entries.forEach { q ->
                            DropdownMenuItem(
                                text = { Text(q.label) },
                                onClick = {
                                    viewModel.updateQuality(q)
                                    showQualityMenu = false
                                },
                                leadingIcon = {
                                    if (q == uiState.videoQuality) {
                                        Icon(Icons.Default.CheckCircle, null)
                                    }
                                }
                            )
                        }
                    }
                }
            }

            HorizontalDivider()

            // Episode list
            LazyColumn(
                modifier = Modifier.fillMaxSize()
            ) {
                itemsIndexed(uiState.episodes) { _, ep ->
                    val isSelected = ep.episodeNumber in uiState.selectedEpisodes
                    val isFree = !ep.isVip

                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 4.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (isSelected)
                                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.3f)
                            else MaterialTheme.colorScheme.surfaceVariant,
                        ),
                        onClick = {
                            viewModel.toggleEpisodeSelection(ep.episodeNumber)
                        }
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            // Status icon
                            if (!isFree) {
                                Icon(
                                    Icons.Default.Lock,
                                    contentDescription = "VIP",
                                    tint = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.size(24.dp),
                                )
                            } else {
                                Icon(
                                    Icons.Default.CheckCircle,
                                    contentDescription = if (isSelected) "已选" else null,
                                    tint = if (isSelected)
                                        MaterialTheme.colorScheme.primary
                                    else MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.size(24.dp),
                                )
                            }

                            Spacer(Modifier.width(12.dp))

                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    ep.displayLabel,
                                    style = MaterialTheme.typography.bodyLarge,
                                    fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                )
                                Row {
                                    if (isFree) {
                                        AssistChip(
                                            onClick = {},
                                            label = { Text("免费", style = MaterialTheme.typography.labelSmall) },
                                            modifier = Modifier.height(24.dp),
                                        )
                                    } else {
                                        AssistChip(
                                            onClick = {},
                                            label = { Text("VIP", style = MaterialTheme.typography.labelSmall) },
                                            colors = AssistChipDefaults.assistChipColors(
                                                containerColor = MaterialTheme.colorScheme.error.copy(alpha = 0.15f),
                                                labelColor = MaterialTheme.colorScheme.error,
                                            ),
                                            modifier = Modifier.height(24.dp),
                                        )
                                    }
                                }
                            }

                            Checkbox(
                                checked = isSelected,
                                onCheckedChange = { viewModel.toggleEpisodeSelection(ep.episodeNumber) },
                            )
                        }
                    }
                }
            }
        }
    }
}
