using System.Collections.Immutable;
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

var options = ProbeOptions.Parse(args);
var contract = options.ContractPath is null
    ? null
    : AbiContract.Load(options.ContractPath);

if (contract is not null)
{
    options = options.WithExactTypes(contract.RequiredTypes.Select(type => type.FullName));
}

var assemblyPath = options.AssemblyPath ?? ProbeOptions.FindDefaultAssembly();

if (!File.Exists(assemblyPath))
{
    throw new FileNotFoundException("STS2 managed assembly was not found.", assemblyPath);
}

var report = AssemblyProbe.Inspect(assemblyPath, options);
var json = JsonSerializer.Serialize(
    report,
    new JsonSerializerOptions
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = true,
    });

if (options.OutputPath is null)
{
    Console.WriteLine(json);
}
else
{
    var fullOutputPath = Path.GetFullPath(options.OutputPath);
    Directory.CreateDirectory(Path.GetDirectoryName(fullOutputPath)!);
    File.WriteAllText(fullOutputPath, json + Environment.NewLine);
    Console.WriteLine($"report={fullOutputPath}");
}

Console.WriteLine($"assembly={report.AssemblyName} {report.AssemblyVersion}");
Console.WriteLine($"game_version={report.GameVersion ?? "unknown"}");
Console.WriteLine($"sha256={report.Sha256}");
Console.WriteLine($"matched_types={report.Types.Count}");

if (contract is not null)
{
    var errors = contract.Validate(report);
    Console.WriteLine($"contract={Path.GetFullPath(options.ContractPath!)}");
    Console.WriteLine($"compatible={errors.Count == 0}");

    if (errors.Count > 0)
    {
        foreach (var error in errors)
        {
            Console.Error.WriteLine($"contract_error={error}");
        }

        Environment.ExitCode = 2;
    }
}

internal sealed record ProbeOptions(
    string? AssemblyPath,
    string? OutputPath,
    string? ContractPath,
    bool PublicOnly,
    IReadOnlyList<string> NamespacePrefixes,
    IReadOnlySet<string> ExactTypes)
{
    private static readonly string[] DefaultPrefixes =
    [
        "MegaCrit.Sts2.Core.AutoSlay",
        "MegaCrit.Sts2.Core.Combat",
        "MegaCrit.Sts2.Core.GameActions",
        "MegaCrit.Sts2.Core.Map",
        "MegaCrit.Sts2.Core.Random",
        "MegaCrit.Sts2.Core.Runs",
    ];

    private static readonly string[] DefaultTypes =
    [
        "MegaCrit.Sts2.Core.Models.CardModel",
        "MegaCrit.Sts2.Core.Models.CreatureModel",
        "MegaCrit.Sts2.Core.Models.MonsterModel",
        "MegaCrit.Sts2.Core.Entities.Players.Player",
        "MegaCrit.Sts2.Core.Entities.Cards.CardPile",
        "MegaCrit.Sts2.Core.Entities.Cards.CardPlay",
    ];

    public static ProbeOptions Parse(string[] arguments)
    {
        string? assemblyPath = null;
        string? outputPath = null;
        string? contractPath = null;
        var publicOnly = false;
        var prefixes = new List<string>();
        var exactTypes = new HashSet<string>(StringComparer.Ordinal);

        for (var index = 0; index < arguments.Length; index++)
        {
            switch (arguments[index])
            {
                case "--assembly":
                    assemblyPath = RequireValue(arguments, ref index, "--assembly");
                    break;
                case "--out":
                    outputPath = RequireValue(arguments, ref index, "--out");
                    break;
                case "--contract":
                    contractPath = RequireValue(arguments, ref index, "--contract");
                    break;
                case "--prefix":
                    prefixes.Add(RequireValue(arguments, ref index, "--prefix"));
                    break;
                case "--type":
                    exactTypes.Add(RequireValue(arguments, ref index, "--type"));
                    break;
                case "--public-only":
                    publicOnly = true;
                    break;
                case "--help":
                case "-h":
                    PrintHelp();
                    Environment.Exit(0);
                    break;
                default:
                    throw new ArgumentException($"Unknown argument: {arguments[index]}");
            }
        }

        if (prefixes.Count == 0 && exactTypes.Count == 0)
        {
            prefixes.AddRange(DefaultPrefixes);
            exactTypes.UnionWith(DefaultTypes);
        }

        return new ProbeOptions(
            assemblyPath,
            outputPath,
            contractPath,
            publicOnly,
            prefixes,
            exactTypes);
    }

    public ProbeOptions WithExactTypes(IEnumerable<string> typeNames)
    {
        var combined = new HashSet<string>(ExactTypes, StringComparer.Ordinal);
        combined.UnionWith(typeNames);
        return this with { ExactTypes = combined };
    }

    public bool Matches(string fullTypeName)
    {
        return ExactTypes.Contains(fullTypeName)
            || NamespacePrefixes.Any(prefix =>
                fullTypeName.Equals(prefix, StringComparison.Ordinal)
                || fullTypeName.StartsWith(prefix + ".", StringComparison.Ordinal));
    }

    public static string FindDefaultAssembly()
    {
        var configured = Environment.GetEnvironmentVariable("STS2_ASSEMBLY_PATH");
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return Path.GetFullPath(configured);
        }

        var managedDir = Environment.GetEnvironmentVariable("Sts2ManagedDir");
        if (!string.IsNullOrWhiteSpace(managedDir))
        {
            return Path.GetFullPath(Path.Combine(managedDir, "sts2.dll"));
        }

        if (OperatingSystem.IsWindows())
        {
            var gameDir = Environment.GetEnvironmentVariable("STS2_GAME_DIR");
            gameDir = string.IsNullOrWhiteSpace(gameDir)
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                    "Steam", "steamapps", "common", "Slay the Spire 2")
                : gameDir;
            return Path.GetFullPath(Path.Combine(gameDir, "data_sts2_windows_x86_64", "sts2.dll"));
        }

        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var macPath = Path.Combine(
            userProfile,
            "Library",
            "Application Support",
            "Steam",
            "steamapps",
            "common",
            "Slay the Spire 2",
            "SlayTheSpire2.app",
            "Contents",
            "Resources",
            "data_sts2_macos_arm64",
            "sts2.dll");

        return macPath;
    }

    private static string RequireValue(string[] arguments, ref int index, string name)
    {
        if (++index >= arguments.Length)
        {
            throw new ArgumentException($"Missing value after {name}.");
        }

        return arguments[index];
    }

    private static void PrintHelp()
    {
        Console.WriteLine(
            """
            Usage: dotnet run --project tools/Sts2.AbiProbe -- [options]

              --assembly <path>  Path to sts2.dll. Defaults to STS2_ASSEMBLY_PATH, Sts2ManagedDir,
                                 or the platform Steam path (Windows also accepts STS2_GAME_DIR).
              --out <path>       Write JSON to this file instead of stdout.
              --contract <path>  Validate required types and members from a JSON ABI contract.
              --prefix <name>    Include a namespace/type prefix. May be repeated.
              --type <name>      Include an exact full type name. May be repeated.
              --public-only      Omit non-public types and members.
            """);
    }
}

internal sealed record AbiContract(
    string Name,
    string? GameVersion,
    string? Sha256,
    IReadOnlyList<RequiredType> RequiredTypes)
{
    public static AbiContract Load(string path)
    {
        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
        {
            throw new FileNotFoundException("ABI contract was not found.", fullPath);
        }

        return JsonSerializer.Deserialize<AbiContract>(
                File.ReadAllText(fullPath),
                new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true,
                    PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
                })
            ?? throw new InvalidDataException($"ABI contract is empty: {fullPath}");
    }

    public IReadOnlyList<string> Validate(AssemblyReport report)
    {
        var errors = new List<string>();

        if (GameVersion is not null
            && !string.Equals(GameVersion, report.GameVersion, StringComparison.Ordinal))
        {
            errors.Add($"game version expected {GameVersion}, found {report.GameVersion ?? "unknown"}");
        }

        if (Sha256 is not null
            && !string.Equals(Sha256, report.Sha256, StringComparison.OrdinalIgnoreCase))
        {
            errors.Add($"assembly sha256 expected {Sha256}, found {report.Sha256}");
        }

        var availableTypes = report.Types.ToDictionary(type => type.FullName, StringComparer.Ordinal);
        foreach (var requiredType in RequiredTypes)
        {
            if (!availableTypes.TryGetValue(requiredType.FullName, out var actualType))
            {
                errors.Add($"missing type {requiredType.FullName}");
                continue;
            }

            foreach (var requiredMember in requiredType.RequiredMembers)
            {
                var matched = actualType.Members.Any(member =>
                    string.Equals(member.Kind, requiredMember.Kind, StringComparison.Ordinal)
                    && string.Equals(member.Name, requiredMember.Name, StringComparison.Ordinal)
                    && (requiredMember.Signature is null
                        || string.Equals(member.Signature, requiredMember.Signature, StringComparison.Ordinal))
                    && (requiredMember.Visibility is null
                        || string.Equals(member.Visibility, requiredMember.Visibility, StringComparison.Ordinal)));

                if (!matched)
                {
                    var expectedSignature = requiredMember.Signature is null
                        ? string.Empty
                        : $" {requiredMember.Signature}";
                    errors.Add(
                        $"missing member {requiredType.FullName}::{requiredMember.Kind} "
                        + $"{requiredMember.Name}{expectedSignature}");
                }
            }
        }

        return errors;
    }
}

internal sealed record RequiredType(
    string FullName,
    IReadOnlyList<RequiredMember> RequiredMembers);

internal sealed record RequiredMember(
    string Kind,
    string Name,
    string? Signature = null,
    string? Visibility = null);

internal static class AssemblyProbe
{
    public static AssemblyReport Inspect(
        string assemblyPath,
        ProbeOptions options)
    {
        using var stream = File.OpenRead(assemblyPath);
        using var peReader = new PEReader(stream, PEStreamOptions.LeaveOpen);
        var reader = peReader.GetMetadataReader();
        var signatureProvider = new StringSignatureProvider();
        var assembly = reader.GetAssemblyDefinition();
        var module = reader.GetModuleDefinition();

        var types = new List<TypeReport>();
        foreach (var typeHandle in reader.TypeDefinitions)
        {
            var type = reader.GetTypeDefinition(typeHandle);
            var fullName = MetadataNames.GetFullTypeName(reader, typeHandle);
            if (!options.Matches(fullName))
            {
                continue;
            }

            if (options.PublicOnly && !IsPublic(type.Attributes))
            {
                continue;
            }

            types.Add(InspectType(reader, typeHandle, signatureProvider, options.PublicOnly));
        }

        types.Sort(static (left, right) => string.CompareOrdinal(left.FullName, right.FullName));

        stream.Position = 0;
        var sha256 = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();

        return new AssemblyReport(
            Path.GetFullPath(assemblyPath),
            reader.GetString(assembly.Name),
            assembly.Version.ToString(),
            reader.GetGuid(module.Mvid).ToString("D"),
            sha256,
            ReadGameVersion(assemblyPath),
            options.PublicOnly,
            options.NamespacePrefixes,
            options.ExactTypes.Order().ToArray(),
            types);
    }

    private static TypeReport InspectType(
        MetadataReader reader,
        TypeDefinitionHandle handle,
        StringSignatureProvider signatureProvider,
        bool publicOnly)
    {
        var type = reader.GetTypeDefinition(handle);
        var members = new List<MemberReport>();

        foreach (var fieldHandle in type.GetFields())
        {
            var field = reader.GetFieldDefinition(fieldHandle);
            if (publicOnly && !IsPublic(field.Attributes))
            {
                continue;
            }

            members.Add(new MemberReport(
                "field",
                reader.GetString(field.Name),
                field.DecodeSignature(signatureProvider, genericContext: null),
                GetVisibility(field.Attributes),
                field.Attributes.HasFlag(FieldAttributes.Static)));
        }

        foreach (var propertyHandle in type.GetProperties())
        {
            var property = reader.GetPropertyDefinition(propertyHandle);
            var accessors = property.GetAccessors();
            var accessorHandles = new[] { accessors.Getter, accessors.Setter }
                .Where(static accessor => !accessor.IsNil)
                .ToArray();
            var isPublic = accessorHandles.Any(accessor =>
                IsPublic(reader.GetMethodDefinition(accessor).Attributes));

            if (publicOnly && !isPublic)
            {
                continue;
            }

            var visibility = accessorHandles.Length == 0
                ? "unknown"
                : accessorHandles
                    .Select(accessor => GetVisibility(reader.GetMethodDefinition(accessor).Attributes))
                    .OrderByDescending(VisibilityRank)
                    .First();
            var isStatic = accessorHandles.Length > 0
                && reader.GetMethodDefinition(accessorHandles[0]).Attributes.HasFlag(MethodAttributes.Static);
            var signature = property.DecodeSignature(signatureProvider, genericContext: null);
            var formatted = signature.ParameterTypes.Length == 0
                ? signature.ReturnType
                : $"{signature.ReturnType} [{string.Join(", ", signature.ParameterTypes)}]";

            members.Add(new MemberReport(
                "property",
                reader.GetString(property.Name),
                formatted,
                visibility,
                isStatic));
        }

        foreach (var methodHandle in type.GetMethods())
        {
            var method = reader.GetMethodDefinition(methodHandle);
            if (publicOnly && !IsPublic(method.Attributes))
            {
                continue;
            }

            var signature = method.DecodeSignature(signatureProvider, genericContext: null);
            var name = reader.GetString(method.Name);
            var genericCount = method.GetGenericParameters().Count;
            if (genericCount > 0)
            {
                name += $"``{genericCount}";
            }

            members.Add(new MemberReport(
                "method",
                name,
                $"{signature.ReturnType} ({string.Join(", ", signature.ParameterTypes)})",
                GetVisibility(method.Attributes),
                method.Attributes.HasFlag(MethodAttributes.Static)));
        }

        members.Sort(static (left, right) =>
        {
            var kind = string.CompareOrdinal(left.Kind, right.Kind);
            return kind != 0 ? kind : string.CompareOrdinal(left.Name, right.Name);
        });

        return new TypeReport(
            MetadataNames.GetFullTypeName(reader, handle),
            GetTypeKind(type.Attributes),
            GetVisibility(type.Attributes),
            type.BaseType.IsNil ? null : MetadataNames.GetTypeName(reader, type.BaseType),
            members);
    }

    private static string? ReadGameVersion(string assemblyPath)
    {
        var resourceDirectory = Directory.GetParent(Path.GetDirectoryName(assemblyPath)!)?.FullName;
        if (resourceDirectory is null)
        {
            return null;
        }

        var releaseInfoPath = Path.Combine(resourceDirectory, "release_info.json");
        if (!File.Exists(releaseInfoPath))
        {
            return null;
        }

        var root = JsonNode.Parse(File.ReadAllText(releaseInfoPath));
        return root?["version"]?.GetValue<string>();
    }

    private static bool IsPublic(TypeAttributes attributes)
    {
        var visibility = attributes & TypeAttributes.VisibilityMask;
        return visibility is TypeAttributes.Public or TypeAttributes.NestedPublic;
    }

    private static bool IsPublic(MethodAttributes attributes) =>
        (attributes & MethodAttributes.MemberAccessMask) == MethodAttributes.Public;

    private static bool IsPublic(FieldAttributes attributes) =>
        (attributes & FieldAttributes.FieldAccessMask) == FieldAttributes.Public;

    private static string GetTypeKind(TypeAttributes attributes)
    {
        if (attributes.HasFlag(TypeAttributes.Interface))
        {
            return "interface";
        }

        return "type";
    }

    private static string GetVisibility(TypeAttributes attributes)
    {
        return (attributes & TypeAttributes.VisibilityMask) switch
        {
            TypeAttributes.Public => "public",
            TypeAttributes.NestedPublic => "public",
            TypeAttributes.NestedFamily => "protected",
            TypeAttributes.NestedFamORAssem => "protected_internal",
            TypeAttributes.NestedAssembly => "internal",
            TypeAttributes.NestedFamANDAssem => "private_protected",
            TypeAttributes.NestedPrivate => "private",
            _ => "internal",
        };
    }

    private static string GetVisibility(MethodAttributes attributes)
    {
        return (attributes & MethodAttributes.MemberAccessMask) switch
        {
            MethodAttributes.Public => "public",
            MethodAttributes.Family => "protected",
            MethodAttributes.FamORAssem => "protected_internal",
            MethodAttributes.Assembly => "internal",
            MethodAttributes.FamANDAssem => "private_protected",
            MethodAttributes.Private => "private",
            _ => "private_scope",
        };
    }

    private static string GetVisibility(FieldAttributes attributes)
    {
        return (attributes & FieldAttributes.FieldAccessMask) switch
        {
            FieldAttributes.Public => "public",
            FieldAttributes.Family => "protected",
            FieldAttributes.FamORAssem => "protected_internal",
            FieldAttributes.Assembly => "internal",
            FieldAttributes.FamANDAssem => "private_protected",
            FieldAttributes.Private => "private",
            _ => "private_scope",
        };
    }

    private static int VisibilityRank(string visibility) => visibility switch
    {
        "public" => 6,
        "protected_internal" => 5,
        "protected" => 4,
        "internal" => 3,
        "private_protected" => 2,
        "private" => 1,
        _ => 0,
    };
}

internal static class MetadataNames
{
    public static string GetFullTypeName(MetadataReader reader, TypeDefinitionHandle handle)
    {
        var definition = reader.GetTypeDefinition(handle);
        var name = reader.GetString(definition.Name);
        var declaringType = definition.GetDeclaringType();
        if (!declaringType.IsNil)
        {
            return GetFullTypeName(reader, declaringType) + "+" + name;
        }

        var typeNamespace = reader.GetString(definition.Namespace);
        return string.IsNullOrEmpty(typeNamespace) ? name : typeNamespace + "." + name;
    }

    public static string GetTypeName(MetadataReader reader, EntityHandle handle)
    {
        return handle.Kind switch
        {
            HandleKind.TypeDefinition => GetFullTypeName(reader, (TypeDefinitionHandle)handle),
            HandleKind.TypeReference => GetTypeReferenceName(reader, (TypeReferenceHandle)handle),
            HandleKind.TypeSpecification => "<type-specification>",
            _ => $"<{handle.Kind}>",
        };
    }

    public static string GetTypeReferenceName(MetadataReader reader, TypeReferenceHandle handle)
    {
        var reference = reader.GetTypeReference(handle);
        var name = reader.GetString(reference.Name);
        var typeNamespace = reader.GetString(reference.Namespace);
        return string.IsNullOrEmpty(typeNamespace) ? name : typeNamespace + "." + name;
    }
}

internal sealed class StringSignatureProvider : ISignatureTypeProvider<string, object?>
{
    public string GetArrayType(string elementType, ArrayShape shape) =>
        elementType + "[" + new string(',', Math.Max(0, shape.Rank - 1)) + "]";

    public string GetByReferenceType(string elementType) => elementType + "&";

    public string GetFunctionPointerType(MethodSignature<string> signature) =>
        $"fnptr({string.Join(", ", signature.ParameterTypes)}) -> {signature.ReturnType}";

    public string GetGenericInstantiation(string genericType, ImmutableArray<string> typeArguments) =>
        $"{genericType}<{string.Join(", ", typeArguments)}>";

    public string GetGenericMethodParameter(object? genericContext, int index) => $"!!{index}";

    public string GetGenericTypeParameter(object? genericContext, int index) => $"!{index}";

    public string GetModifiedType(string modifier, string unmodifiedType, bool isRequired) =>
        unmodifiedType;

    public string GetPinnedType(string elementType) => elementType + " pinned";

    public string GetPointerType(string elementType) => elementType + "*";

    public string GetPrimitiveType(PrimitiveTypeCode typeCode) => typeCode switch
    {
        PrimitiveTypeCode.Boolean => "bool",
        PrimitiveTypeCode.Byte => "byte",
        PrimitiveTypeCode.Char => "char",
        PrimitiveTypeCode.Double => "double",
        PrimitiveTypeCode.Int16 => "short",
        PrimitiveTypeCode.Int32 => "int",
        PrimitiveTypeCode.Int64 => "long",
        PrimitiveTypeCode.IntPtr => "nint",
        PrimitiveTypeCode.Object => "object",
        PrimitiveTypeCode.SByte => "sbyte",
        PrimitiveTypeCode.Single => "float",
        PrimitiveTypeCode.String => "string",
        PrimitiveTypeCode.TypedReference => "typedref",
        PrimitiveTypeCode.UInt16 => "ushort",
        PrimitiveTypeCode.UInt32 => "uint",
        PrimitiveTypeCode.UInt64 => "ulong",
        PrimitiveTypeCode.UIntPtr => "nuint",
        PrimitiveTypeCode.Void => "void",
        _ => typeCode.ToString(),
    };

    public string GetSZArrayType(string elementType) => elementType + "[]";

    public string GetTypeFromDefinition(
        MetadataReader reader,
        TypeDefinitionHandle handle,
        byte rawTypeKind) => MetadataNames.GetFullTypeName(reader, handle);

    public string GetTypeFromReference(
        MetadataReader reader,
        TypeReferenceHandle handle,
        byte rawTypeKind) => MetadataNames.GetTypeReferenceName(reader, handle);

    public string GetTypeFromSpecification(
        MetadataReader reader,
        object? genericContext,
        TypeSpecificationHandle handle,
        byte rawTypeKind) => reader
            .GetTypeSpecification(handle)
            .DecodeSignature(this, genericContext);
}

internal sealed record AssemblyReport(
    string AssemblyPath,
    string AssemblyName,
    string AssemblyVersion,
    string ModuleVersionId,
    string Sha256,
    string? GameVersion,
    bool PublicOnly,
    IReadOnlyList<string> NamespacePrefixes,
    IReadOnlyList<string> ExactTypes,
    IReadOnlyList<TypeReport> Types);

internal sealed record TypeReport(
    string FullName,
    string Kind,
    string Visibility,
    string? BaseType,
    IReadOnlyList<MemberReport> Members);

internal sealed record MemberReport(
    string Kind,
    string Name,
    string Signature,
    string Visibility,
    bool IsStatic);
