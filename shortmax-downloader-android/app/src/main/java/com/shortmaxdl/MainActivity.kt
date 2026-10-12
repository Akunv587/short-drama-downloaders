package com.shortmaxdl

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.shortmaxdl.ui.*
import com.shortmaxdl.ui.theme.ShortMaxDLTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            ShortMaxDLTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val navController = rememberNavController()
                    val viewModel: MainViewModel = viewModel()

                    NavHost(
                        navController = navController,
                        startDestination = "main",
                    ) {
                        // Page 1: Main (URL input)
                        composable("main") {
                            MainScreen(
                                viewModel = viewModel,
                                onNavigateToEpisodes = {
                                    navController.navigate("episodes") {
                                        launchSingleTop = true
                                    }
                                },
                                onNavigateToSettings = {
                                    navController.navigate("settings")
                                },
                            )
                        }

                        // Page 2: Episode List
                        composable("episodes") {
                            EpisodeListScreen(
                                viewModel = viewModel,
                                onBack = {
                                    viewModel.goBack()
                                    navController.popBackStack()
                                },
                                onNavigateToDownloads = {
                                    navController.navigate("downloads") {
                                        launchSingleTop = true
                                    }
                                },
                            )
                        }

                        // Page 3: Download Progress
                        composable("downloads") {
                            DownloadScreen(
                                viewModel = viewModel,
                                onBack = {
                                    navController.popBackStack()
                                },
                            )
                        }

                        // Page 4: Settings
                        composable("settings") {
                            SettingsScreen(
                                viewModel = viewModel,
                                onBack = {
                                    navController.popBackStack()
                                },
                                onNavigateToLogin = {
                                    navController.navigate("login")
                                },
                            )
                        }

                        // Page 5: WebView Login
                        composable("login") {
                            WebViewLoginScreen(
                                viewModel = viewModel,
                                onBack = {
                                    navController.popBackStack()
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}
