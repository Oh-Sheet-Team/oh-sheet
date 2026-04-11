import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../theme.dart';

/// Optional compile-time override (e.g. Docker `--dart-define=APP_VERSION=…`).
/// When empty, the label comes from [PackageInfo] (semver + build from `pubspec.yaml`).
const _envVersion = String.fromEnvironment('APP_VERSION', defaultValue: '');

class VersionFooter extends StatelessWidget {
  const VersionFooter({super.key});

  static String _displayFromEnv() {
    final raw = _envVersion.trim();
    if (raw.isEmpty) return '';
    final normalized = raw.startsWith('v') ? raw.substring(1) : raw;
    return 'v$normalized';
  }

  static String _displayFromPackageInfo(PackageInfo info) {
    final build = info.buildNumber.trim();
    final hasBuild = build.isNotEmpty && build != '0';
    return hasBuild ? 'v${info.version}+$build' : 'v${info.version}';
  }

  @override
  Widget build(BuildContext context) {
    final fromEnv = _displayFromEnv();
    if (fromEnv.isNotEmpty) {
      return Text(
        fromEnv,
        style: TextStyle(
          fontSize: 11,
          color: OhSheetColors.mutedText.withValues(alpha: 0.5),
          fontWeight: FontWeight.w500,
        ),
      );
    }

    return FutureBuilder<PackageInfo>(
      future: PackageInfo.fromPlatform(),
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const SizedBox(height: 14);
        }
        final label = _displayFromPackageInfo(snapshot.data!);
        return Text(
          label,
          style: TextStyle(
            fontSize: 11,
            color: OhSheetColors.mutedText.withValues(alpha: 0.5),
            fontWeight: FontWeight.w500,
          ),
        );
      },
    );
  }
}
